# The data files are no longer noupdate : the flag Odoo keeps on each record is reset
# before they load, so that an update applies them (datasets, panels, tiles).
MODELS = ("kt.dataset", "kt.panel", "kt.dataset.line")


def migrate(cr, version):
    cr.execute(
        "UPDATE ir_model_data SET noupdate = false "
        "WHERE module = 'kpiten_commercial_data' AND model IN %s",
        (MODELS,),
    )
