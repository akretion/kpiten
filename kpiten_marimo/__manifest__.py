{
    "name": "KpiTen Marimo",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Open the Marimo front of KpiTen from the Odoo menu",
    "description": """
KpiTen Marimo
=============
Everything Odoo needs for the Marimo front (marimo-kpiten), which explores the data of KpiTen with the rights of the user instead of drawing the dashboards :

* a "Marimo" entry in the KpiTen menu : it opens the front through the SSO of
  kpiten (a session for the current user),
* the service parameter of the front (`kpiten_marimo_service` : its urls).

kpiten itself stays free of it : without this module there is no Marimo menu.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten"],
    "data": [
        "data/ir_config_parameter.xml",
        "views/kpiten_marimo.xml",
    ],
    "installable": True,
}
