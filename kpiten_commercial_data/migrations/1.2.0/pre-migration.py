# The panels Sales and Purchase are in kpiten_kpi (their tiles are there) : when it is
# installed, their xml ids become its own, the same records stay ; without it, they
# go (empty panels) with the update of this module.

PANELS = ("panel_sale", "panel_purchase")


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = 'kpiten_kpi'"
        " AND state IN ('installed', 'to upgrade')"
    )
    if not cr.fetchone():
        return
    cr.execute(
        "UPDATE ir_model_data SET module = 'kpiten_kpi'"
        " WHERE module = 'kpiten_commercial_data' AND name IN %s",
        (PANELS,),
    )
