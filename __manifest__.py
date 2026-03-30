# -*- coding: utf-8 -*-
{
    'name': 'Lot Maal Transfer',
    'version': '16.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Transfer cut pieces inventory to Lot Maal (LM) products for discounted sale',
    'description': 'Transfer cut pieces from multiple products into a Lot Maal (LM) product. Bypasses negative stock checks. Accessible from Inventory menu and Sale Quotations.',
    'author': 'Aspire Analytica',
    'depends': [
        'stock',
        'sale_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/lot_maal_security.xml',
        'data/lot_maal_data.xml',
        'wizard/lot_maal_wizard_views.xml',
        'views/lot_maal_transfer_views.xml',
        'views/stock_menu_views.xml',
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
