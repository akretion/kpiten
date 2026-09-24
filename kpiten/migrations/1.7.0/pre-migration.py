# The preview of a KPI is in kpiten : its form shows it as Shiny draws it (an iframe).
# kpiten_preview, which computed it in Odoo with kpiten-core, is gone : uninstalled by
# this update (Odoo removes a module `to remove` while it loads the others), with
# parquet_sample (polars) when nothing else needs it.


def migrate(cr, version):
    cr.execute(
        "UPDATE ir_module_module SET state = 'to remove'"
        " WHERE name = 'kpiten_preview' AND state IN ('installed', 'to upgrade')"
    )
    cr.execute("""
        UPDATE ir_module_module SET state = 'to remove'
         WHERE name = 'parquet_sample' AND state IN ('installed', 'to upgrade')
           AND NOT EXISTS (
               SELECT 1 FROM ir_module_module_dependency d
                 JOIN ir_module_module m ON m.id = d.module_id
                WHERE d.name = 'parquet_sample' AND m.name != 'kpiten_preview'
                  AND m.state IN ('installed', 'to upgrade')
           )
        """)
