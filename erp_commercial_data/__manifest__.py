{
    "name": "ERP Commercial Demo Data",
    "version": "18.0.2.0.0",
    "category": "Tools",
    "summary": "A French company selling abroad : users, customers, vendors, sales and purchases over 3 years",
    "description": """
Demo data of a French company selling and buying abroad, independent of KpiTen :
the company (France, euro, French chart of accounts), the users and their rights
(login `first.last`, password the first name), products, customers and vendors, then
about 10 000 sales orders and 3 000 purchase orders over 3 years, with a realistic
lifecycle (states, late deliveries, lead times). The lifecycle is forced in SQL :
meant for dashboards, not for accounting.

The generators are the steps of `erp.demo.generator` (`_demo_steps`) ; they run at
install, and again with `generate_all_demo_data`. The volume : erp_commercial_data_big.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "sale_stock",
        "purchase",
        "purchase_stock",
        "l10n_fr_account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/demo_company.xml",
        "data/demo_users.xml",
        "data/demo_orders.xml",
        "data/demo_sales.xml",
        "data/demo_purchases.xml",
    ],
    "installable": True,
}
