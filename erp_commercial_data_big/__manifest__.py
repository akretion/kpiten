{
    "name": "ERP Commercial Demo Data (big volume)",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Hundreds of thousands of sales orders (4 lines, several years) for volume tests",
    "description": """
Extends erp_commercial_data with `generate_big_sale_demo` : sales orders of
4 lines over several years (default 500 000 over 3 years), for dashboards and
extraction tests at scale.

The orders are inserted in SQL by batches, cloned from a few real orders
created through the ORM (so every column is valid) : a million lines take
minutes, not hours. Amounts follow Odoo's rules (one percent tax, excluded from
the price, rounded per line) and are checked against the ORM on a sample.
As in erp_commercial_data the lifecycle (delivery, invoicing) is forced : no
real deliveries nor customer invoices, meant for dashboards only.

Install : creates `erp_commercial_data_big.initial_orders` orders (system
parameter, default 500 000). They follow the world of erp_commercial_data : each
order its zone (customers, team, currency, price list, fiscal position), channel
and season.

Add sales afterwards, from an Odoo shell (see `make add-sales` in bi/) :

    env.ref("erp_commercial_data_big.demo_generator_sale_big").add_big_sales(100000)
""",
    "author": "Akretion",
    "license": "LGPL-3",
    # erp_commercial_data : its PRODUCTS and helpers are used directly
    "depends": ["erp_commercial_data"],
    "data": ["data/demo_big_sales.xml"],
    "installable": True,
}
