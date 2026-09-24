"""What differs between the Odoo series this module runs on (see
`scripts/downgrade.py` for the views, which are written for the latest series).

Only the Python side lives here : one place to look when a new series comes.
"""

from odoo import models, release
from odoo.tools.safe_eval import safe_eval

try:
    import tomllib  # Python 3.11+
except ImportError:  # Odoo 16 runs on older Pythons
    import tomli as tomllib

try:  # kpiten-spec : the syntax of the tiles, standard library only (Python 3.8+)
    from kpiten_spec import edit as spec_edit
    from kpiten_spec import spec
    from kpiten_spec.spec import is_sql
    from kpiten_spec.validate import validate_display, validate_toml
except ImportError:  # not installed : no validation of the tiles, no tile builder
    spec = spec_edit = is_sql = validate_display = validate_toml = None

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
    if not hasattr(query, "get_sql"):  # 18+ : Query.select() alone
        # the SQL object is given whole : its `code` / `params` are gone in 20
        return records.env.cr.mogrify(query.select()).decode()
    query.order = None  # only the ids are kept : no need to sort them
    sql, params = query.select()
    return records.env.cr.mogrify(sql, params).decode()


def get_param(env, key: str, default=None):
    """A system parameter (text), as the superuser reads it : `get_param` until
    Odoo 18, `get_str` after."""
    params = env["ir.config_parameter"].sudo()
    if hasattr(params, "get_str"):
        return params.get_str(key) or default
    return params.get_param(key, default)


def set_param(env, key: str, value) -> None:
    """Set a system parameter (text) : `set_param` until Odoo 18, `set_str` after."""
    params = env["ir.config_parameter"].sudo()
    if hasattr(params, "set_str"):
        params.set_str(key, value)
    else:
        params.set_param(key, value)


def set_modifier(node, attribute: str, field: str, operator: str, value) -> None:
    """`attribute` (invisible, required) of a view `node` when `field operator value`
    (`kind != 'graph'`) : an expression from Odoo 17, `attrs` (a domain) before."""
    if SERIES >= 17:  # a python expression : `=` of a domain is `==`
        python = "==" if operator == "=" else operator
        node.set(attribute, f"{field} {python} {value!r}")
        return
    attrs = safe_eval(node.get("attrs") or "{}")
    attrs[attribute] = [(field, operator, value)]
    node.set("attrs", repr(attrs))


def groups_field(env) -> str:
    """The groups of a user : `groups_id` until Odoo 18, `group_ids` after."""
    return "group_ids" if "group_ids" in env["res.users"]._fields else "groups_id"


def sql_constraints(namespace: dict, **constraints) -> None:
    """Declare the SQL constraints of a model, from its class body :

        sql_constraints(locals(), user_uniq=("unique(user_id)", "One theme a user."))

    `models.Constraint` attributes from Odoo 19 (`_sql_constraints` is ignored
    there), `_sql_constraints` before."""
    if hasattr(models, "Constraint"):
        for name, (definition, message) in constraints.items():
            namespace[f"_{name}"] = models.Constraint(definition, message)
    else:
        namespace["_sql_constraints"] = [
            (name, definition, message)
            for name, (definition, message) in constraints.items()
        ]


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
    "get_param",
    "groups_field",
    "ids_sql",
    "readable_fields",
    "set_modifier",
    "set_param",
    "spec",
    "spec_edit",
    "sql_constraints",
    "tomllib",
    "validate_toml",
]
