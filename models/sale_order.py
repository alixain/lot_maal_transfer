# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaleOrder(models.Model):
    """Extend sale.order to show related LM transfers."""
    _inherit = 'sale.order'

    lot_maal_count = fields.Integer(
        string='LM Transfers',
        compute='_compute_lot_maal_count',
    )

    def _compute_lot_maal_count(self):
        for order in self:
            order.lot_maal_count = self.env['lot.maal.transfer'].search_count([
                ('sale_order_id', '=', order.id),
            ])

    def action_view_lot_maal_transfers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lot Maal Transfers'),
            'res_model': 'lot.maal.transfer',
            'view_mode': 'tree,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }
