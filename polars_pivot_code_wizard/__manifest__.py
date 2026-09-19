{
    "name": "Polars Pivot Code Generator",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Generate Polars pivot code and preview it from a live sample of any model's data",
    "description": """
Polars Pivot Code Generator
============================
A wizard that:

1. Extracts a heterogeneous 20-record sample of any Odoo model into a Parquet file
   (done by the parquet_sample module).
2. Lets you pick the Index / Column / Value fields directly from the
   Parquet file's columns (no more typing field names by hand).
3. Generates the corresponding Polars ``.pivot()`` Python snippet.
4. Actually runs that pivot on the sample data and previews the result
   as a Markdown table.

Requires the 'polars' Python package on the Odoo server.
""",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["base", "parquet_sample"],
    "external_dependencies": {
        "python": ["polars"],
    },
    "data": [
        "security/ir.model.access.csv",
        "wizards/polars_code_wizard_views.xml",
    ],
    "installable": True,
}
