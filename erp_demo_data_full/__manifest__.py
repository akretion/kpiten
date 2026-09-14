{
    "name": "ERP Full Demo Data",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Full ERP demo data (large volume, only to be installed on demo instances)",
    "description": """
Runs erp_demo_generator.generate_demo_data(months=12) : 12 products over
12 months with the complete sales/purchase cycle (invoices, receipts).
Do not install together with erp_demo_generator's own light dataset
unless extra volume is desired (documents are appended).
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["erp_demo_generator"],
    "data": ["data/demo_orders_full.xml"],
    "installable": True,
}
