# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class LotMaalWizard(models.TransientModel):
    """
    Wizard (popup) to initiate a Lot Maal transfer.
    Called from:
      - Inventory > Lot Maal > New LM Transfer (button)
      - Sale Order / Quotation form (Lot Maal button in header)
    """
    _name = 'lot.maal.wizard'
    _description = 'Initiate Lot Maal Transfer'

    lm_product_id = fields.Many2one(
        'product.product',
        string='Destination LM Product',
        required=True,
        domain=[('type', '=', 'product')],
        ondelete='restrict',
        help='Select the Lot Maal (LM) product that will receive the transferred inventory.',
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
        'lot.maal.wizard.line',
        'wizard_id',
        string='Source Products',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Related Quotation',
        readonly=True,
        ondelete='set null',
    )
    notes = fields.Text(string='Notes / Remarks')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # If opened from a sale order context
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')
        if active_model == 'sale.order' and active_id:
            res['sale_order_id'] = active_id
        return res

    def action_confirm(self):
        """
        Validate inputs, create a lot.maal.transfer record, and confirm it.
        This directly manipulates inventory, bypassing negative stock checks.
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add at least one source product before confirming.'))
        if self.lm_product_id in self.line_ids.mapped('product_id'):
            raise UserError(_(
                'The LM destination product "%s" cannot also be a source product.'
            ) % self.lm_product_id.display_name)

        # Create the permanent transfer record
        transfer = self.env['lot.maal.transfer'].create({
            'lm_product_id': self.lm_product_id.id,
            'location_id': self.location_id.id,
            'dest_location_id': self.dest_location_id.id,
            'sale_order_id': self.sale_order_id.id if self.sale_order_id else False,
            'notes': self.notes,
            'line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'qty': line.qty,
            }) for line in self.line_ids],
        })

        # Confirm (validates stock moves, updates quants)
        transfer.action_confirm()

        # Return action to open the created transfer record
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lot Maal Transfer'),
            'res_model': 'lot.maal.transfer',
            'res_id': transfer.id,
            'view_mode': 'form',
            'target': 'current',
        }


class LotMaalWizardLine(models.TransientModel):
    """
    Transient lines for the wizard — mirrors lot.maal.transfer.line
    but lives only for the duration of the wizard session.
    """
    _name = 'lot.maal.wizard.line'
    _description = 'Lot Maal Wizard Line'

    wizard_id = fields.Many2one(
        'lot.maal.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
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
        string='Quantity',
        required=True,
        default=1.0,
    )
    current_stock = fields.Float(
        string='On Hand',
        compute='_compute_current_stock',
        help='Current stock at source location. Transfer will proceed even if negative.',
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.depends('product_id', 'wizard_id.location_id')
    def _compute_current_stock(self):
        for line in self:
            if line.product_id and line.wizard_id.location_id:
                quant = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.wizard_id.location_id.id),
                ], limit=1)
                line.current_stock = quant.quantity if quant else 0.0
            else:
                line.current_stock = 0.0
