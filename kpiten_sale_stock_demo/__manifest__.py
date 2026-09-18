{
    "name": "KPI Ten Sale Demo Data",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Sales orders with a realistic lifecycle (late deliveries, lead times) for dashboards",
    "description": """
Extends erp_demo_generator with `generate_sale_stock_demo` : sales orders
over several years, spread over the salespeople (not the buyer), in varied
states (draft, sent, cancelled, confirmed) with delivery delays, late and
partial deliveries and invoicing statuses.

The lifecycle is forced in SQL (no real deliveries nor customer invoices) :
it is meant to feed sales dashboards, not accounting.

It also declares the four KPI cards of the Odoo "Sales" dashboard (Quotations,
Orders, Revenue, Average Order) in the KPI Ten "Sales" panel.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["erp_demo_generator", "sale_stock", "kpiten_demo"],
    "data": ["data/demo_sales.xml", "data/tiles.xml"],
    "installable": True,
}
