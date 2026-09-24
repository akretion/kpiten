{
    "name": "KpiTen KPI",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "The Sales and Purchase panels and their KPI (tiles)",
    "description": """
The tiles of the panels of kpiten_commercial_data : cards, graphs, tables, some in SQL,
one drawn by the plugin perspective-kpiten. Loaded as data (not demo data), and not
noupdate : an update of the module applies the files.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten_commercial_data"],
    "data": [
        "data/panels.xml",
        "data/tiles.xml",
        "data/tiles_sale.xml",
        "data/tiles_sql.xml",
        "data/tiles_perspective.xml",
    ],
    "installable": True,
}
