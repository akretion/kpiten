{
    "name": "KpiTen Shiny",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Open the Shiny front of KpiTen from the Odoo menu",
    "description": """
KpiTen Shiny
============
Everything Odoo needs for the Shiny front (shiny-kpiten), the KpiTen dashboards drawn with Shiny :

* a "Shiny" entry in the KpiTen menu : it opens the front through the SSO of
  kpiten (a session for the current user),
* the service parameter of the front (`kpiten_shiny_service` : its urls).

kpiten itself stays free of it : without this module there is no Shiny menu.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten"],
    "data": [
        "data/ir_config_parameter.xml",
        "views/kpiten_shiny.xml",
    ],
    "installable": True,
}
