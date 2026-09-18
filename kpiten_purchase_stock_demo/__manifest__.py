{
    "name": "KPI Ten Purchase Demo Data",
    "version": "18.0.1.0.0",
    "category": "Purchase",
    "summary": "Purchase orders with a realistic lifecycle (late RFQs, lead times) for dashboards",
    "description": """
Extends erp_demo_generator with `generate_purchase_stock_demo` : purchase
orders over several years, all placed by the buyer, in varied states (draft,
sent, to approve, cancelled, confirmed, done) with confirmation and receipt
delays, late receipts and partial receipts.

The lifecycle is forced in SQL (no real receipts nor vendor bills) : it is
meant to feed purchase dashboards, not accounting.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["erp_demo_generator", "purchase_stock"],
    "data": ["data/demo_purchases.xml"],
    "installable": True,
}
