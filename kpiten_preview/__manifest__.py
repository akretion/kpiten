{
    "name": "KpiTen Preview",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "See a KPI tile in Odoo, computed on a sample of its dataset",
    "description": """
KpiTen Preview
==============
A "Preview" button on a tile (kt.dataset.line) shows the tile as the dashboards draw it,
computed on a small sample of the dataset (parquet_sample) with kpiten-core : the card,
graph, pivot, union or data table, and the error when the definition is wrong.

Everything that draws a KPI inside Odoo is here : kpiten itself stays free of it.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten", "parquet_sample"],
    "data": [
        "security/ir.model.access.csv",
        "views/kt_line_preview.xml",
    ],
    "installable": True,
}
