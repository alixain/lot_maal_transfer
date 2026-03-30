# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LotMaalTransfer(models.Model):
    """
    Stores the history of all Lot Maal (LM) transfer operations.
    Each record represents one LM initiation event.
    """
    _name = 'lot.maal.transfer'
    _description = 'Lot Maal Transfer'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    lm_product_id = fields.Many2one(
        'product.product',
        string='LM (Lot Maal) Product',
        required=True,
        ondelete='restrict',
        tracking=True,
        help='The destination Lot Maal product that will receive the aggregated inventory.',
    )
    lm_product_uom_id = fields.Many2one(
        'uom.uom',
        string='LM Unit of Measure',
        related='lm_product_id.uom_id',
        readonly=True,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self.env.ref('stock.stock_location_stock', raise_if_not_found=False),
        ondelete='restrict',
    )
    dest_location_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self.env.ref('stock.stock_location_stock', raise_if_not_found=False),
        ondelete='restrict',
    )
    line_ids = fields.One2many(
        'lot.maal.transfer.line',
        'transfer_id',
        string='Source Products',
    )
    total_qty = fields.Float(
        string='Total Transferred Qty',
        compute='_compute_total_qty',
        store=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Source Quotation',
        readonly=True,
        ondelete='set null',
        help='Quotation from which this LM transfer was initiated.',
    )
    picking_ids = fields.One2many(
        'stock.picking',
        'lot_maal_transfer_id',
        string='Stock Transfers',
        readonly=True,
    )
    picking_count = fields.Integer(
        string='Transfers',
        compute='_compute_picking_count',
    )
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    @api.depends('line_ids.qty')
    def _compute_total_qty(self):
        for rec in self:
            rec.total_qty = sum(rec.line_ids.mapped('qty'))

    def _compute_picking_count(self):
        for rec in self:
            rec.picking_count = len(rec.picking_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('lot.maal.transfer') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        """
        Create actual stock moves:
        - One move per source product line → to LM product destination
        - Force-allows negative stock by using sudo + no quant check
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft transfers can be confirmed.'))
        if not self.line_ids:
            raise UserError(_('Please add at least one source product line.'))

        # Find or create the internal picking type
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', self.company_id.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_('No internal operation type found. Please configure a warehouse first.'))

        # Create one picking for all moves
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': picking_type.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.dest_location_id.id,
            'origin': self.name,
            'lot_maal_transfer_id': self.id,
            'note': _('Lot Maal Transfer: %s') % self.name,
        })

        # Create negative-source moves: source product → virtual/scrap → (deduct)
        # and destination move: virtual → LM product (add)
        # Strategy: We directly manipulate quants via sudo to bypass negative checks.
        # For each source line, reduce the quant of source product and add to LM product.

        for line in self.line_ids:
            if line.qty <= 0:
                raise UserError(_('Quantity must be greater than 0 for product: %s') % line.product_id.display_name)

            # Create stock move from source product location to LM product location
            move = self.env['stock.move'].sudo().create({
                'name': _('LM: %s → %s') % (line.product_id.display_name, self.lm_product_id.display_name),
                'product_id': line.product_id.id,
                'product_uom': line.product_uom_id.id,
                'product_uom_qty': line.qty,
                'location_id': self.location_id.id,
                'location_dest_id': self.dest_location_id.id,
                'picking_id': picking.id,
                'state': 'draft',
            })

        # Validate picking with allow_negative context
        # This bypasses the negative stock warning/error
        picking.with_context(
            immediate_transfer=True,
            skip_backorder=True,
            skip_immediate=True,
        ).sudo().action_confirm()

        # Force set all move lines qty_done = demand qty
        for move in picking.move_ids:
            move.sudo().write({'quantity_done': move.product_uom_qty})

        # Validate without negative stock check
        picking.with_context(
            skip_backorder=True,
            skip_immediate=True,
            no_recompute=True,
        ).sudo()._action_done()

        # Now add inventory directly to LM product using quant
        total_lm_qty = sum(self.line_ids.mapped('qty'))
        lm_quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.lm_product_id.id),
            ('location_id', '=', self.dest_location_id.id),
        ], limit=1)

        if lm_quant:
            lm_quant.sudo().write({
                'quantity': lm_quant.quantity + total_lm_qty,
            })
        else:
            self.env['stock.quant'].sudo().create({
                'product_id': self.lm_product_id.id,
                'location_id': self.dest_location_id.id,
                'quantity': total_lm_qty,
            })

        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Done transfers cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.ensure_one()
        if self.state != 'cancelled':
            raise UserError(_('Only cancelled transfers can be reset to draft.'))
        self.write({'state': 'draft'})

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('lot_maal_transfer_id', '=', self.id)],
        }


class LotMaalTransferLine(models.Model):
    """
    One line = one source product being transferred into the LM product.
    """
    _name = 'lot.maal.transfer.line'
    _description = 'Lot Maal Transfer Line'

    transfer_id = fields.Many2one(
        'lot.maal.transfer',
        string='Transfer',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Source Product',
        required=True,
        ondelete='restrict',
        domain=[('type', '=', 'product')],
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
    )
    qty = fields.Float(
        string='Quantity to Transfer',
        required=True,
        default=1.0,
    )
    current_stock = fields.Float(
        string='Current Stock',
        compute='_compute_current_stock',
        help='Current on-hand quantity at the source location.',
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.depends('product_id', 'transfer_id.location_id')
    def _compute_current_stock(self):
        for line in self:
            if line.product_id and line.transfer_id.location_id:
                quant = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.transfer_id.location_id.id),
                ], limit=1)
                line.current_stock = quant.quantity if quant else 0.0
            else:
                line.current_stock = 0.0


class StockPicking(models.Model):
    """Extend stock.picking to link back to the LM transfer."""
    _inherit = 'stock.picking'

    lot_maal_transfer_id = fields.Many2one(
        'lot.maal.transfer',
        string='Lot Maal Transfer',
        readonly=True,
        ondelete='set null',
        index=True,
    )
