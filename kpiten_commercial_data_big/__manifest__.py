{
    "name": "KpiTen Commercial Data (big volume)",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "The volume of the big demo sales set in the KpiTen configuration, and generated from it in the background",
    "description": """
A tab « Demo data » in the KpiTen configuration (kt.config) : how many sales
orders, lines per order, years of history, shares of confirmed, delivered and
invoiced orders ; and a button that generates them (erp_commercial_data_big :
the orders, their pickings, stock and invoices) in the background, by a cron,
the progress shown in the tab. Each generation adds to the orders already there.

Installed, it keeps erp_commercial_data_big from generating its orders at its
own installation : the configuration decides.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten", "erp_commercial_data_big"],
    "data": [
        "data/ir_cron.xml",
        "views/kt_config.xml",
    ],
    "installable": True,
}
