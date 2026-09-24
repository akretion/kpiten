# `kt.dataset.line` becomes `kt.kpi` (and the wizard of kpiten_preview,
# `kt.dataset.line.preview`, `kt.kpi.preview`) : their tables, the many2many of the
# tiles with the groups, the reflection of Odoo (ir.model, ir.model.fields, the xml ids)
# and the records that name the model. Plain SQL : the same on every series.

MODELS = [  # the longest first : `kt.dataset.line` is in `kt.dataset.line.preview`
    ("kt.dataset.line.preview", "kt.kpi.preview"),
    ("kt.dataset.line", "kt.kpi"),
]
# (table, column) that hold a model name, when the table has the column
MODEL_COLUMNS = [
    ("ir_model", "model"),
    ("ir_model_fields", "model"),
    ("ir_model_fields", "relation"),
    ("ir_model_data", "model"),
    ("ir_act_window", "res_model"),
    ("ir_ui_view", "model"),
    ("ir_attachment", "res_model"),
    ("ir_filters", "model_id"),
    ("ir_act_server", "model_name"),
    ("ir_act_report_xml", "model"),
    ("ir_translation", "res_model"),
    ("mail_message", "model"),
    ("mail_followers", "res_model"),
    ("mail_activity", "res_model"),
]


def _table(model: str) -> str:
    return model.replace(".", "_")


def _exists(cr, table: str) -> bool:
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def _has_column(cr, table: str, column: str) -> bool:
    cr.execute(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return bool(cr.fetchone())


def _rename_table(cr, old: str, new: str) -> None:
    """The table, its sequence, its constraints and its indexes named after it."""
    cr.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
    cr.execute(f'ALTER SEQUENCE IF EXISTS "{old}_id_seq" RENAME TO "{new}_id_seq"')
    cr.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass"
        " AND conname LIKE %s",
        (new, old.replace("_", r"\_") + r"\_%"),
    )
    for (name,) in cr.fetchall():
        cr.execute(
            f'ALTER TABLE "{new}" RENAME CONSTRAINT "{name}"'
            f' TO "{new}{name[len(old):]}"'
        )
    cr.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexname LIKE %s",
        (new, old.replace("_", r"\_") + r"\_%"),
    )
    for (name,) in cr.fetchall():
        cr.execute(f'ALTER INDEX "{name}" RENAME TO "{new}{name[len(old):]}"')


def migrate(cr, version):
    old_line, new_line = _table("kt.dataset.line"), _table("kt.kpi")
    if not _exists(cr, old_line) or _exists(cr, new_line):
        return  # a new base, or already done
    for old, new in MODELS:
        if _exists(cr, _table(old)):
            _rename_table(cr, _table(old), _table(new))
    # the many2many of the tiles with the groups (its table is named after the model)
    old_rel, new_rel = f"{old_line}_res_groups_rel", f"{new_line}_res_groups_rel"
    if _exists(cr, old_rel):
        cr.execute(f'ALTER TABLE "{old_rel}" RENAME TO "{new_rel}"')
        cr.execute(
            f'ALTER TABLE "{new_rel}" RENAME COLUMN "{old_line}_id" TO "{new_line}_id"'
        )
        cr.execute(
            "UPDATE ir_model_fields SET relation_table = %s WHERE relation_table = %s",
            (new_rel, old_rel),
        )
        cr.execute(
            "UPDATE ir_model_fields SET column1 = %s WHERE column1 = %s",
            (f"{new_line}_id", f"{old_line}_id"),
        )
        cr.execute(
            "UPDATE ir_model_relation SET name = %s WHERE name = %s", (new_rel, old_rel)
        )
    # the records that name the models
    for old, new in MODELS:
        for table, column in MODEL_COLUMNS:
            if _exists(cr, table) and _has_column(cr, table, column):
                cr.execute(
                    f'UPDATE "{table}" SET "{column}" = %s WHERE "{column}" = %s',
                    (new, old),
                )
    # the xml ids named after the model (model_, field_, access_, the views...) : the
    # records stay the same, the module update does not recreate them
    cr.execute(
        "UPDATE ir_model_data SET name = replace(name, 'kt_dataset_line', 'kt_kpi')"
        " WHERE name LIKE %s",
        (r"%kt\_dataset\_line%",),
    )
    cr.execute(
        "UPDATE ir_model_constraint SET name = replace(name, %s, %s) WHERE name LIKE %s",
        (old_line, new_line, old_line.replace("_", r"\_") + r"\_%"),
    )
