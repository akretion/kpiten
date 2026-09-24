"""SQL generation for direct Postgres extraction of a dataset model.

The kpiten app builds its parquet snapshot straight from Postgres (via
connectorx / polars), not through the Odoo ORM. This module turns a dataset
model into its SELECT :

- direct stored fields of the model, many2one included as their bare foreign
  key id (no join, no display name : kpiten-core resolves it in bulk, see
  `kpiten_core.resolve`, since Odoo's own `display_name`/`name_get` logic is
  what a SQL guess of the "right" text column can't reliably reproduce)
- relational dot-paths (`user_id.name`, `categ_id.name`...) joined through
  `_follow_relational_fields`

`build_select` returns a bare SELECT statement (used by the app through
connectorx), `create_sql_view` wraps it in a `CREATE OR REPLACE VIEW` for the
persistent-view mode.
"""

from __future__ import annotations

from psycopg2 import sql

from odoo.exceptions import ValidationError
from odoo.tools.translate import _

# Map an Odoo domain operator to a SQL operator.
_OPS = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    "<": "<",
    ">=": ">=",
    "<=": "<=",
    "in": "IN",
    "not in": "NOT IN",
    "like": "LIKE",
    "not like": "NOT LIKE",
    "ilike": "ILIKE",
    "not ilike": "NOT ILIKE",
    "=like": "LIKE",
    "=ilike": "ILIKE",
}

# Operators matching a pattern (value is a raw pattern, not auto-wrapped).
_PATTERN_OPS = {"like", "ilike", "not like", "not ilike"}
_EQ_PATTERN_OPS = {"=like", "=ilike"}


def _alias(expr, name: str):
    """Alias an expression as `name` without the `.as()` psycopg2 helper.

    `.as` became a reserved keyword in Python 3.14, so we compose the `AS`
    clause manually.
    """
    return expr + sql.SQL(" AS ") + sql.Identifier(name)


def _render(comp) -> str:
    """Render a psycopg2 sql composition to a string without a connection.

    `Composable.as_string` requires a real psycopg2 connection/cursor, which
    is not guaranteed when the model method runs through the JSON-RPC worker.
    """
    if isinstance(comp, sql.Composed):
        return "".join(_render(part) for part in comp)
    if isinstance(comp, sql.Identifier):
        # quote the identifier with double quotes, escaping inner quotes
        return '"' + comp._wrapped[0].replace('"', '""') + '"'
    if isinstance(comp, sql.Literal):
        return "'" + str(comp._wrapped).replace("'", "''") + "'"
    # plain SQL text segment
    return comp._wrapped if hasattr(comp, "_wrapped") else str(comp)


def _sql_value(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _m2o_id(value):
    """Extract the id from a many2one domain value."""
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value


def _leaf_sql(model, field, op, value, m2o_fields, m2o_suffix="_", table=None) -> str:
    sqlop = _OPS.get(op)
    if not sqlop:
        raise ValidationError(_("Unsupported domain operator '%s'." % op))
    # A many2one domain leaf targets the foreign key : the real column in the
    # Odoo table (no suffix) or the de-normalized `<field>_` id used by the
    # parquet convention.
    column = f"{field}{m2o_suffix}" if field in m2o_fields else field
    if table:
        # qualified : the joined tables have write_date, create_date, name...
        column = f'"{table}"."{column}"'
    if op in ("in", "not in"):
        values = ", ".join(_sql_value(v) for v in value)
        return f"{column} {sqlop} ({values})"
    if op in _PATTERN_OPS or op in _EQ_PATTERN_OPS:
        pattern = value if isinstance(value, str) else str(value)
        if op in _PATTERN_OPS and "%" not in pattern:
            pattern = f"%{pattern}%"
        return f"{column} {sqlop} {_sql_value(pattern)}"
    if field in m2o_fields:
        value = _m2o_id(value)
    return f"{column} {sqlop} {_sql_value(value)}"


def _parse_domain(model, domain, i, m2o_fields, m2o_suffix="_", table=None):
    tok = domain[i]
    if tok == "&":
        left, i = _parse_domain(model, domain, i + 1, m2o_fields, m2o_suffix, table)
        right, i = _parse_domain(model, domain, i, m2o_fields, m2o_suffix, table)
        return f"({left} AND {right})", i
    if tok == "|":
        left, i = _parse_domain(model, domain, i + 1, m2o_fields, m2o_suffix, table)
        right, i = _parse_domain(model, domain, i, m2o_fields, m2o_suffix, table)
        return f"({left} OR {right})", i
    if tok == "!":
        left, i = _parse_domain(model, domain, i + 1, m2o_fields, m2o_suffix, table)
        return f"(NOT {left})", i
    field, op, value = tok
    return _leaf_sql(model, field, op, value, m2o_fields, m2o_suffix, table), i + 1


def _domain_to_sql(model, domain, m2o_suffix="_", table=None) -> str:
    """Convert an Odoo domain to a SQL `where` clause.

    With `table`, the columns are qualified by it (needed when the query
    joins other tables, as `build_select` does).
    """
    m2o_fields = {fname for fname, f in model._fields.items() if f.type == "many2one"}
    if not domain:
        return ""
    parts = []
    i = 0
    while i < len(domain):
        sql, i = _parse_domain(model, domain, i, m2o_fields, m2o_suffix, table)
        parts.append(sql)
    return " AND ".join(parts) if len(parts) > 1 else parts[0]


def _table_columns(cr, table: str) -> dict[str, str]:
    """Real Postgres columns of a table, mapped to their data type."""
    cr.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (table,),
    )
    return {row[0]: row[1] for row in cr.fetchall()}


def build_select(env, model: str, domain: list = None, order: str = "") -> str:
    """Build the SELECT of `model` (the rows of `domain`, sorted by `order`).

    Many2one fields are emitted as their bare foreign key id (a plain column
    of the model's own table, no join needed) ; kpiten-core resolves the
    display name in bulk afterwards. Relational dot-paths are joined from
    `_follow_relational_fields`.
    """
    model_obj = env[model]
    table = model_obj._table
    real_cols = set(_table_columns(env.cr, table))
    m2o_cols = {
        fname
        for fname, f in model_obj._fields.items()
        if f.type == "many2one" and fname in real_cols
    }
    scalar_cols = [
        fname
        for fname in env["kt"]._get_model_direct_fields(model)
        if fname in real_cols and fname != "id"
    ]
    id_col = sql.Identifier(table)

    selects = [id_col + sql.SQL(".") + sql.Identifier("id")]
    joins = []

    def add_scalar(col, alias=None):
        alias = alias or col
        expr = id_col + sql.SQL(".") + sql.Identifier(col)
        return _alias(expr, alias)

    for col in scalar_cols:
        selects.append(add_scalar(col))

    # relational dot-paths from kt (user_id.name, categ_id.name, ...)
    relational = env["kt"]._get_relational_paths_for_model(model)
    alias_counter = 0

    def join_alias(field):
        nonlocal alias_counter
        alias_counter += 1
        return sql.Identifier(f"{table}_{field}_{alias_counter}")

    for path in sorted(relational):
        segments = path.split(".")
        # only walk relations whose root is a real stored m2o column
        if segments[0] not in m2o_cols:
            continue
        prev_expr = id_col
        cur_model = model_obj
        parent_of = None  # (parent_model, link_field) when cur_model inherits
        for seg in segments[:-1]:
            field = cur_model._fields.get(seg)
            if not field or field.type != "many2one":
                break
            comodel = field.comodel_name
            if not comodel:
                break
            # the m2o column `seg` may live in cur_model's own table or in the
            # delegating-inherited parent ; pick the reference that stores it.
            if parent_of and seg not in set(_table_columns(env.cr, cur_model._table)):
                ref = parent_alias
            else:
                ref = prev_expr
            table = env[comodel]._table
            target_alias = join_alias(seg)
            joins.append(
                sql.SQL("LEFT JOIN ")
                + sql.Identifier(table)
                + sql.SQL(" AS ")
                + target_alias
                + sql.SQL(" ON ")
                + target_alias
                + sql.SQL(".")
                + sql.Identifier("id")
                + sql.SQL(" = ")
                + ref
                + sql.SQL(".")
                + sql.Identifier(seg)
            )
            prev_expr = target_alias
            cur_model = env[comodel]
            parent_alias = None
            parent_of = None
            if getattr(cur_model, "_inherits", None):
                parent_model, link_field = next(iter(cur_model._inherits.items()))
                parent = env[parent_model]
                parent_alias = join_alias(seg)
                joins.append(
                    sql.SQL("LEFT JOIN ")
                    + sql.Identifier(parent._table)
                    + sql.SQL(" AS ")
                    + parent_alias
                    + sql.SQL(" ON ")
                    + parent_alias
                    + sql.SQL(".")
                    + sql.Identifier("id")
                    + sql.SQL(" = ")
                    + prev_expr
                    + sql.SQL(".")
                    + sql.Identifier(link_field)
                )
                parent_of = (parent_model, link_field)
        # reference the final column on the table that actually stores it
        final_ref = prev_expr
        if parent_of:
            parent_model, _ = parent_of
            parent_cols = set(_table_columns(env.cr, env[parent_model]._table))
            if segments[-1] in parent_cols:
                final_ref = parent_alias
        selects.append(
            _alias(final_ref + sql.SQL(".") + sql.Identifier(segments[-1]), path)
        )

    # `table` is reassigned while walking the joins : use the model's own one
    where = _domain_to_sql(
        model_obj, domain or [], m2o_suffix="", table=model_obj._table
    )
    query = (
        sql.SQL("SELECT ") + sql.SQL(", ").join(selects) + sql.SQL(" FROM ") + id_col
    )
    for join in joins:
        query = query + sql.SQL(" ") + join
    if where:
        query = query + sql.SQL(" WHERE ") + sql.SQL(where)
    if order:
        query = query + sql.SQL(" ORDER BY ") + sql.SQL(order)
    return _render(query)


def create_sql_view(env, model: str) -> str:
    """Create (or replace) a persistent SQL view exposing `model` as kt data."""
    query = build_select(env, model)
    view = sql.Identifier(f"kpiten_{model.replace('.', '_')}")
    stmt = sql.SQL("CREATE OR REPLACE VIEW ") + view + sql.SQL(" AS ") + sql.SQL(query)
    env.cr.execute(stmt)
    return _render(view)
