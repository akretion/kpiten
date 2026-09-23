{
    "name": "KPI Ten Commercial Demo Generator",
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

The tiles of the "Sales" panel that show these orders are in
kpiten_commercial_data (data/tiles_sale.xml).
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["erp_demo_generator", "sale_stock", "kpiten_commercial_data"],
    "data": ["data/demo_sales.xml"],
    "installable": True,
}
