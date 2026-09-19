{
    "name": "Parquet Sample",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "A small sample of any Odoo model, as a polars DataFrame or a Parquet file",
    "description": """
Parquet Sample
==============
`parquet.sample` draws a small sample of the records of any model, spread over its
history, and turns it into a polars DataFrame or a Parquet file. It is done with the
ORM, as the current user : the sample holds only what the user may read, and only the
stored fields (what the KpiTen store holds).

It only generates the sample. What uses it lives in other modules :
the pivot code wizard (polars_pivot_code_wizard), the KPI preview of the tiles
(kpiten_preview), and any tool that needs some real rows to work on.

Requires the 'polars' Python package on the Odoo server.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["base"],
    "external_dependencies": {"python": ["polars"]},
    "data": [],
    "installable": True,
}
