"""What differs between the Odoo series this module runs on (see
`scripts/downgrade.py` for the views, which are written for the latest series).

Only the Python side lives here : one place to look when a new series comes.
"""

from odoo import release

try:
    import tomllib  # Python 3.11+
except ImportError:  # Odoo 16 runs on older Pythons
    import tomli as tomllib

try:
    from kpiten_core.validate import validate_toml
except (
    ImportError
):  # kpiten_core needs Python 3.12 : not on the older series, no validation
    validate_toml = None

SERIES = release.version_info[0]

# name of the list view / view mode : `tree` before Odoo 18
LIST = "list" if SERIES >= 18 else "tree"


def can_read(records) -> bool:
    """Whether the user of the environment may read the model (`has_access` is 18+)."""
    if hasattr(records, "has_access"):
        return records.has_access("read")
    return records.check_access_rights("read", raise_exception=False)


def ids_sql(records) -> str:
    """The `SELECT id` of the records the user may read, the record rules applied.

    `Query.select()` is a `(sql, params)` pair before Odoo 18, an SQL object after.
    """
    query = records._search([])
    if not hasattr(query, "get_sql"):  # 18 : Query.select() alone
        sql = query.select()
        return records.env.cr.mogrify(sql.code, sql.params).decode()
    query.order = None  # only the ids are kept : no need to sort them
    sql, params = query.select()
    return records.env.cr.mogrify(sql, params).decode()


def readable_fields(env, model: str) -> list[str]:
    """The names of the fields of `model` the user of `env` may read (`groups=`)."""
    fields = env[model]._fields
    if all(hasattr(field, "is_accessible") for field in fields.values()):
        return [name for name, field in fields.items() if field.is_accessible(env)]
    return list(env[model].fields_get(attributes=["type"]))


__all__ = [
    "LIST",
    "SERIES",
    "can_read",
    "ids_sql",
    "readable_fields",
    "tomllib",
    "validate_toml",
]
