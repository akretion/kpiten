{
    "name": "KPI Ten Sale Demo Data (big volume)",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Hundreds of thousands of sales orders (4 lines, several years) for volume tests",
    "description": """
Extends kpiten_commercial_demo_generator with `generate_big_sale_demo` : sales orders of
4 lines over several years (default 300 000 over 4 years), for dashboards and
extraction tests at scale.

The orders are inserted in SQL by batches, cloned from a few real orders
created through the ORM (so every column is valid) : a million lines take
minutes, not hours. Amounts follow Odoo's rules (one percent tax, excluded from
the price, rounded per line) and are checked against the ORM on a sample.
As in kpiten_commercial_demo_generator the lifecycle (delivery, invoicing) is forced : no
real deliveries nor customer invoices, meant for dashboards only.

Install : creates `kpiten_sale_stock_demo_big.initial_orders` orders (system
parameter, default 300 000).

Add sales afterwards, from an Odoo shell (see `make add-sales` in bi/) :

    env.ref("kpiten_sale_stock_demo_big.demo_generator_sale_big").add_big_sales(100000)
""",
    "author": "Akretion",
    "license": "LGPL-3",
    # erp_demo_generator : its PRODUCTS and helpers are used directly
    "depends": ["erp_demo_generator", "kpiten_commercial_demo_generator", "sale_stock"],
    "data": ["data/demo_big_sales.xml"],
    "installable": True,
}
