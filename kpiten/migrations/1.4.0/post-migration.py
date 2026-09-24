# "Main", the empty panel of the module, goes, unless someone put tiles on it
def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'kpiten' AND name = 'panel_main' AND model = 'kt.panel'
        """)
    row = cr.fetchone()
    if not row:
        return
    cr.execute(
        "SELECT count(*) FROM kt_kpi WHERE panel_id = %s", row
    )  # renamed by 1.5.0 (pre)
    if cr.fetchone()[0]:
        return
    cr.execute("DELETE FROM kt_panel WHERE id = %s", row)
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'kpiten' AND name = 'panel_main'"
    )
