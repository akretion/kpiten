{
    "name": "KpiTen NiceGUI",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Open the NiceGUI front of KpiTen from the Odoo menu",
    "description": """
KpiTen NiceGUI
==============
Everything Odoo needs for the NiceGUI front (nicegui-kpiten), the KpiTen dashboards drawn with NiceGUI :

* a "NiceGUI" entry in the KpiTen menu : it opens the front through the SSO of
  kpiten (a session for the current user),
* the service parameter of the front (`kpiten_nicegui_service` : its urls).

kpiten itself stays free of it : without this module there is no NiceGUI menu.
""",
    "author": "Akretion",
    "license": "LGPL-3",
    "depends": ["kpiten"],
    "data": [
        "data/ir_config_parameter.xml",
        "views/kpiten_nicegui.xml",
    ],
    "installable": True,
}
