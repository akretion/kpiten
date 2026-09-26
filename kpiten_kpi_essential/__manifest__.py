{
    "name": "KpiTen KPI essentials",
    "version": "18.0.1.3.0",
    "category": "Sales",
    "summary": "One tile per kind and option : the reference of the syntax, for dev and tests",
    "description": """
An « Essentials » panel with a representative tile of each kind (card, graph, pivot,
union, data in SQL and in polars) and of each option of their definition, and the
derived tables the tiles read by their name (data/derived.xml). It is the
base of the development (a light base) and of the non regression tests when the syntax
evolves ; kpiten_kpi stays the demo close to the dashboards of Odoo.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": [
        "kpiten_commercial_data",
        "erp_commercial_data",
    ],
    "data": ["data/panel.xml", "data/tiles.xml", "data/derived.xml"],
    "installable": True,
}
