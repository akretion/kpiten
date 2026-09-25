"""Check a tile in Odoo (a card, a graph, a pivot) : the same rows, counted by Odoo in
its pivot view, grouped as the tile, with the rights of the user.

The link opens the route `/kpiten/check` of the module : it makes the pivot view of the
model on a domain, then redirects to it. The domain says the same as the tile :

- the period of the panel on its date field(s), in UTC days like the store ;
- the `where` of the tile, the dimensions chosen and the filters the AI made (SQL), turned
  into a domain (`where_domain`) ; a name of a many2one is turned into its ids, from the
  store, so that `"user_id" IN ('Marie Stourne')` is exact in Odoo too.

When a condition has no domain (a computed column, a function, a filter of the panel that
reaches the table through another), the link falls back on the ids of the rows the tile
counts : Odoo then counts the same records, but does not check the filter itself.
"""

import datetime
import json
import logging
from urllib.parse import urlencode

import polars as pl
import sqlglot
from sqlglot import exp

from kpiten_core import config as settings
from kpiten_core import dfnorm, env, filters, links, spec, tiles

logger = logging.getLogger(__name__)

# an url longer than that is not followed by every server (nginx : 8k for a line)
MAX_URL = 6000

# what Odoo shows, when it is not the value of the tile itself
HINTS = {
    "mean": "Odoo shows the sum and the count : the mean is the sum / the count",
    "median": "Odoo shows the sum and the count : not the median",
    "min": "Odoo shows the sum and the count : not the minimum",
    "max": "Odoo shows the sum and the count : not the maximum",
}
CURRENCY_HINT = (
    "Some rows are in another currency : KpiTen converts the amounts to the "
    "currency of the company, Odoo adds them up as they are"
)

COMPARISONS = {
    exp.EQ: "=",
    exp.NEQ: "!=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
}
FLIPPED = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "=": "=", "!=": "!="}


class Untranslatable(ValueError):
    """A condition that has no Odoo domain."""


def _column(node) -> str | None:
    """`partner_id`, `"order_id.date_order"` or `order_id.date_order` : the field path."""
    if isinstance(node, exp.Column):
        return ".".join(part.name for part in node.parts)
    return None


def _value(node):
    """The Python value of a literal (a date written `DATE '...'` stays text)."""
    if isinstance(node, exp.Paren):
        return _value(node.this)
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        number = float(node.this)
        return int(number) if number.is_integer() and "." not in node.this else number
    if isinstance(node, exp.Boolean):
        return node.this
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Neg):
        return -_value(node.this)
    if isinstance(node, exp.Cast) and isinstance(node.this, exp.Literal):
        return node.this.this
    raise Untranslatable(f"not a value : {node.sql()}")


class _Translator:
    """SQL conditions on the columns of a table -> an Odoo domain (prefix notation)."""

    def __init__(self, frame: pl.LazyFrame | None, computed=()):
        self.frame = frame
        self.schema = frame.collect_schema() if frame is not None else {}
        self.computed = set(computed)

    def field(self, name: str) -> str:
        if name in self.computed:
            raise Untranslatable(f"{name} is computed by the tile, not stored in Odoo")
        # `partner_id_` : the id of the many2one `partner_id`
        if name.endswith("_") and name[:-1] in self.schema:
            return name[:-1]
        return name

    def is_m2o_name(self, name: str) -> bool:
        """The name of a many2one, whose id is `<name>_` (see `dfnorm`)."""
        return self.schema.get(name) == pl.String and f"{name}_" in self.schema

    def ids_of(self, name: str, values: list) -> list[int]:
        """The ids of the records of a many2one named `values` (the names are data)."""
        ids = (
            self.frame.filter(pl.col(name).is_in(values))
            .select(pl.col(f"{name}_").drop_nulls().unique().sort())
            .collect()
        )
        return ids.to_series().to_list()

    def leaf(self, name: str, operator: str, value) -> list:
        """One condition ; a name of a many2one becomes its ids."""
        field = self.field(name)
        if value is None:
            if operator not in ("=", "!="):
                raise Untranslatable(f"{name} {operator} NULL")
            return [(field, operator, False)]
        if self.is_m2o_name(name) and operator in ("=", "!=", "in", "not in"):
            values = value if isinstance(value, list) else [value]
            positive = operator in ("=", "in")
            leaf = (field, "in" if positive else "not in", self.ids_of(name, values))
            return [leaf] if positive else ["&", leaf, (field, "!=", False)]
        if operator in ("!=", "not in"):
            # SQL leaves the empty ones out, Odoo keeps them
            return ["&", (field, operator, value), (field, "!=", False)]
        return [(field, operator, value)]

    def domain(self, node) -> list:
        if isinstance(node, exp.Paren):
            return self.domain(node.this)
        if isinstance(node, exp.And):
            return ["&", *self.domain(node.left), *self.domain(node.right)]
        if isinstance(node, exp.Or):
            return ["|", *self.domain(node.left), *self.domain(node.right)]
        if isinstance(node, exp.Not):
            inner = (
                node.this.unnest() if isinstance(node.this, exp.Paren) else node.this
            )
            if isinstance(inner, exp.In):
                return self.is_in(inner, negated=True)
            if isinstance(inner, exp.Is):
                return self.is_null(inner, negated=True)
            return ["!", *self.domain(inner)]
        if type(node) in COMPARISONS:
            operator = COMPARISONS[type(node)]
            name = _column(node.left)
            if name is not None:
                return self.leaf(name, operator, _value(node.right))
            name = _column(node.right)
            if name is not None:
                return self.leaf(name, FLIPPED[operator], _value(node.left))
            raise Untranslatable(f"no column alone in {node.sql()}")
        if isinstance(node, exp.In):
            return self.is_in(node)
        if isinstance(node, exp.Is):
            return self.is_null(node)
        if isinstance(node, exp.Between):
            name = self.column_of(node.this)
            low, high = _value(node.args["low"]), _value(node.args["high"])
            return ["&", *self.leaf(name, ">=", low), *self.leaf(name, "<=", high)]
        if isinstance(node, (exp.Like, exp.ILike)):
            operator = "=like" if isinstance(node, exp.Like) else "=ilike"
            name = self.column_of(node.this)
            if self.is_m2o_name(name):
                raise Untranslatable(f"a pattern on the name of {name}")
            return [(self.field(name), operator, _value(node.expression))]
        if isinstance(node, exp.Boolean):
            return [(1, "=", 1)] if node.this else [(0, "=", 1)]
        raise Untranslatable(f"no domain for {node.sql()}")

    def column_of(self, node) -> str:
        name = _column(node)
        if name is None:
            raise Untranslatable(f"not a column : {node.sql()}")
        return name

    def is_in(self, node, negated=False) -> list:
        if node.args.get("query"):
            raise Untranslatable("a sub-query")
        name = self.column_of(node.this)
        values = [_value(value) for value in node.expressions]
        return self.leaf(name, "not in" if negated else "in", values)

    def is_null(self, node, negated=False) -> list:
        if not isinstance(node.expression, exp.Null):
            raise Untranslatable(f"no domain for {node.sql()}")
        name = self.column_of(node.this)
        return self.leaf(name, "!=" if negated else "=", None)


def where_domain(where: str, frame: pl.LazyFrame | None = None, computed=()) -> list:
    """The Odoo domain of a SQL condition on the rows of `frame` (the table, to find the
    ids of the many2one names). Untranslatable when it has none."""
    try:
        query = sqlglot.parse_one(f"SELECT * FROM self WHERE {where}")
    except sqlglot.errors.ParseError as err:
        raise Untranslatable(str(err)) from err
    return _Translator(frame, computed).domain(query.args["where"].this)


def period_domain(date_fields: list[str], date_value, columns) -> list:
    """The period on the date field(s) the table has. The store keeps the day of a
    datetime in UTC : `< the day after` is the same in Odoo, for a date or a datetime.
    """
    if not date_value:
        return []
    start, end = date_value
    after = end + datetime.timedelta(days=1)
    domain = []
    for field in (f for f in date_fields if f in columns):
        domain += [
            (field, ">=", f"{start:%Y-%m-%d}"),
            (field, "<", f"{after:%Y-%m-%d}"),
        ]
    return domain


def id_ranges(ids) -> str:
    """`1-4,7,9-10` : the ids, short enough for an url."""
    ranges = []
    for i in sorted(set(ids)):
        if ranges and i == ranges[-1][1] + 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def check_url(odoo_url: str, model: str, name: str, **params) -> str | None:
    """The link to `/kpiten/check` (None when too long) ; `params` : `domain` (a
    list), `ids`, `measure`, `groupby`, `colgroupby`."""
    query = {"model": model, "name": name}
    if params.get("domain") is not None:
        query["domain"] = json.dumps(params["domain"])
    if params.get("ids") is not None:
        query["ids"] = id_ranges(params["ids"])
    for key in ("measure", "groupby", "colgroupby"):
        if params.get(key):
            query[key] = params[key]
    url = f"{odoo_url}/kpiten/check?{urlencode(query)}"
    return url if len(url) <= MAX_URL else None


def _other_currency(rows: pl.LazyFrame) -> bool:
    """Whether a row is in a currency the store converted (`dfnorm.to_company_currency`
    divides its amounts by its rate)."""
    schema = rows.collect_schema()
    rate = next((c for c in dfnorm.Df.RATE_COLUMNS if c in schema), None)
    if rate is None:
        return False
    other = pl.col(rate).cast(pl.Float64).is_not_null() & (pl.col(rate) != 1)
    return rows.filter(other).head(1).collect().height > 0


# a derived date column (`date_order.month`) : the grouping of Odoo (`date_order:month`)
DATE_PARTS = ("year", "quarter", "month", "week", "day")
KINDS = ("card", "graph", "pivot")


def _grouping(name: str | None, rows: pl.LazyFrame, grain: str | None = None):
    """The Odoo grouping of a column of a tile : `date_order.month` and a date with a
    `grain` group by that part of the date ; a date alone by day, or by month when the
    graph has too many days (`tiles._bound_dates`)."""
    if not name:
        return None
    schema = rows.collect_schema()
    root, _sep, part = name.rpartition(".")
    if root and part in DATE_PARTS and name not in schema and root in schema:
        return f"{root}:{part}"
    if name in schema and schema[name] in (pl.Date, pl.Datetime):
        if grain:
            return f"{name}:{grain}"
        days = rows.select(pl.col(name).n_unique()).collect().item()
        return f"{name}:{'month' if days > env.tile_max_points else 'day'}"
    return name


def _layout(kind: str, definition: dict, rows: pl.LazyFrame) -> dict:
    """What Odoo shows of a tile : `measure`, `aggregation`, `groupby` (the rows of the
    pivot of Odoo) and `colgroupby` (its columns)."""
    grain = definition.get("grain")
    if kind == "card":
        aggregation = definition.get("aggregation", "count")
        if definition.get("by"):  # the best group : the sum of `measure` by `by`
            aggregation = "sum"
        rows_by, columns_by = definition.get("by"), None
    elif kind == "graph":
        aggregation = definition.get("aggregation", "sum")
        rows_by, columns_by = definition["by"], definition.get("series")
    else:  # pivot : the grain goes to the date among its rows and columns
        aggregation = definition.get("aggregation", "sum")
        rows_by, columns_by = definition["rows"], definition.get("columns")
    measure = definition.get("measure") if aggregation != "count" else None
    return {
        "measure": measure,
        "aggregation": aggregation,
        "groupby": _grouping(rows_by, rows, grain),
        "colgroupby": _grouping(columns_by, rows, grain),
    }


def tile_check(
    line: dict,
    store: dict,
    predicates: list[pl.Expr],
    filter_config: dict,
    date_value,
    conditions: list[str] = (),
    translatable: bool = True,
) -> dict | None:
    """The link that checks a card, a graph or a pivot in Odoo : `{url, how, hints}`,
    `how` is `domain` or `ids` (see the module). `store` is the one the tile reads (the
    AI filter of the tile applied), `predicates` its panel filters ; `conditions` the
    dimensions and the AI filters as SQL (`savetile.dimension_conditions`), which the
    domain adds ; `translatable` False : a filter has no SQL here, only the ids can say
    it. `hints` : why Odoo may show another value (the aggregation, the currencies).
    None when the feature is off, when the tile has no rows, or when neither way
    works."""
    kind = line.get("kind")
    if not settings.feature("open_in_odoo") or kind not in KINDS:
        return None
    definition = spec.load(line["content"], kind)
    table = definition.get("from", line["model"])
    frame = store.get(table)
    if frame is None:
        return None
    frame = frame.lazy()
    columns = set(frame.collect_schema().names())
    computed = set(definition.get("computed") or {})
    rows = tiles.tile_rows(definition, line["model"], store, predicates)
    if rows.head(1).collect().height == 0:
        return None  # nothing to check (or a model the user may not read)
    layout = _layout(kind, definition, rows)
    aggregation = layout.pop("aggregation")
    if layout["measure"] in computed:
        layout["measure"] = None
    measure = layout["measure"]
    odoo_url, name = links.get_odoo_url(), line.get("name") or table
    hints = [HINTS[aggregation]] if measure and aggregation in HINTS else []
    if measure and _other_currency(rows):
        hints.append(CURRENCY_HINT)
    try:
        if not translatable:
            raise Untranslatable("a filter of the panel")
        wheres = [definition["where"]] if definition.get("where") else []
        domain = (
            []
            if definition.get("ignore_period")
            else period_domain(filters.date_fields(filter_config), date_value, columns)
        )
        for where in [*wheres, *conditions]:
            domain += where_domain(tiles.expand_today(where), frame, computed)
        url = check_url(odoo_url, table, name, domain=domain, **layout)
        if url:
            return {"url": url, "how": "domain", "hints": hints}
    except Untranslatable as err:
        logger.info("tile %s checked by its ids : %s", line.get("id"), err)
    if "id" not in columns:
        return None
    ids = rows.select(pl.col("id").drop_nulls()).collect().to_series().to_list()
    url = check_url(odoo_url, table, name, ids=ids, **layout)
    return {"url": url, "how": "ids", "hints": hints} if url else None
