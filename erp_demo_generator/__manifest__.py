{
    "name": "ERP Demo Data Generator",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Generate ERP demo data (sales, purchase orders, users)",
    "description": """
Generic ERP demo data generator, not related to kpi features.
Generate historical sales and purchase orders with salespeople.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["sale_management", "sale_stock", "purchase", "purchase_stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/demo_users.xml",
        "data/demo_orders.xml",
    ],
    "installable": True,
}
