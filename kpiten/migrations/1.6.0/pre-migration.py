# The modules kpiten_shiny, kpiten_nicegui and kpiten_marimo are in kpiten : their xml
# ids (the actions, the menus, the addresses of the fronts) become kpiten's, the same
# records stay ; the three modules are no longer installed.

FRONT_MODULES = ("kpiten_shiny", "kpiten_nicegui", "kpiten_marimo")


def migrate(cr, version):
    cr.execute(
        "UPDATE ir_model_data SET module = 'kpiten' WHERE module IN %s",
        (FRONT_MODULES,),
    )
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name IN %s",
        (FRONT_MODULES,),
    )
