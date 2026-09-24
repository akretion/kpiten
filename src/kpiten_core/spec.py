"""The syntax of the kpi definitions, version 2 (see docs/kpi-syntaxe-v2.md).

One declarative schema per kind (`CARD`, `GRAPH`, `PIVOT`) : each key with its type,
its allowed values, its default and a help text. The same schema checks a definition
(`validate`), and will give the tooltips and the form of a tile builder.

`version = 2` is optional : the version 1 is no longer read (`kpiten_core.migrate`
converts it). The union keeps its own syntax (other changes await it).

Standard library only : Odoo imports this module (Python 3.10, `tomli` then).
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 (Odoo 16, 17)
    import tomli as tomllib

VERSION = 2
DATE_DIFF_RE = re.compile(r"^\s*([\w.]+)\s*-\s*([\w.]+)\s*$")

CARD_AGGREGATIONS = ("count", "sum", "mean", "median", "min", "max")
AGGREGATIONS = ("sum", "count", "mean")
GRAPH_TYPES = ("bar", "line", "area", "point", "pie")
GRAINS = ("month",)


@dataclass(frozen=True)
class Key:
    """A key of a definition. `column` : its value names a column of the dataset."""

    name: str
    type: type = str
    choices: tuple = ()
    default: Any = None
    required: bool = False
    column: bool = False
    help: str = ""


@dataclass(frozen=True)
class Table:
    """A `[table]` of a definition : fixed `keys`, or free keys whose values are of
    type `values` (`[computed]`). `shorthand` : the type the table may be given as
    instead (`compare = true` for `[compare]`)."""

    name: str
    keys: tuple = ()
    values: Optional[type] = None
    shorthand: Optional[type] = None
    help: str = ""


@dataclass(frozen=True)
class Kind:
    name: str
    entries: tuple
    rules: tuple = ()  # (definition) -> message or None

    def entry(self, name: str):
        return next((e for e in self.entries if e.name == name), None)


def _requires_measure(data: dict) -> Optional[str]:
    if data.get("aggregation", "count") != "count" and not data.get("measure"):
        return f"Aggregation '{data['aggregation']}' needs a 'measure'"
    if data.get("by") and not data.get("measure"):
        return "'by' needs a 'measure' to rank the groups"
    return None


# the keys of every kind
VERSION_KEY = Key("version", int, help="2 : this syntax")
WHERE = Key("where", help="SQL condition on the rows, e.g. state = 'sale'")
FROM = Key("from", help="another table of the store than the one of the dataset")
COMPUTED = Table(
    "computed",
    values=str,
    help="computed columns : name = '<date> - <date>' (whole days)",
)
LABELS = Table(
    "labels",
    values=str,
    help="the name shown for a column : amount_untaxed = 'HT'",
)

CARD = Kind(
    "card",
    (
        VERSION_KEY,
        WHERE,
        FROM,
        Key("measure", column=True, help="the column aggregated"),
        Key("aggregation", choices=CARD_AGGREGATIONS, default="count"),
        Key("by", column=True, help="show the best group of this column"),
        Key("unit", help="shown after the value ; 'currency' : the company's"),
        Key("decimals", int, default=0),
        Key("ignore_period", bool, default=False, help="the panel period is ignored"),
        Table(
            "compare",
            keys=(Key("good", choices=("up", "down"), default="up"),),
            shorthand=bool,
            help="compared with the previous period",
        ),
        Table(
            "detail",
            keys=(
                Key("measure", column=True, required=True),
                Key("label", help="after the number"),
            ),
            help="the line under the value of a 'by' card",
        ),
        COMPUTED,
    ),
    rules=(_requires_measure,),
)


def _graph_rules(data: dict) -> Optional[str]:
    if data.get("type") == "pie" and data.get("series"):
        return "A pie has no 'series'"
    if isinstance(data.get("limit"), int) and data["limit"] < 1:
        return "Key 'limit' in graph must be 1 or more"
    return None


GRAPH = Kind(
    "graph",
    (
        VERSION_KEY,
        Key("type", choices=GRAPH_TYPES, default="bar"),
        WHERE,
        FROM,
        Key("by", column=True, required=True, help="the x axis : one bar per value"),
        Key("grain", choices=GRAINS, help="the dates of 'by' grouped by month"),
        Key("measure", column=True, required=True, help="the y axis"),
        Key("aggregation", choices=AGGREGATIONS, default="sum"),
        Key("others", bool, default=False, help="the rest in one « Others » bar"),
        Key("limit", int, help="the biggest bars kept (else TILE_MAX_CATEGORIES)"),
        Key("series", column=True, help="one color per value of this column"),
        Key("stacked", bool, default=False, help="the series one on the other"),
        Key("orientation", choices=("v", "h"), default="v", help="h : horizontal"),
        COMPUTED,
        LABELS,
        Table(
            "plotly",
            keys=(
                Table("layout", values=object, help="given to update_layout"),
                Table("traces", values=object, help="given to update_traces"),
            ),
            help="given as is to plotly : what kpiten does not say",
        ),
    ),
    rules=(_graph_rules,),
)

FORMATS = ("number", "integer", "currency", "percent")
CELL_FORMAT = (
    Key("format", choices=FORMATS, default="number", help="how the cells are written"),
    Key("decimals", int, default=0),
)
TABLE = Table(
    "table",
    keys=CELL_FORMAT
    + (
        Key("totals", bool, default=False, help="a « Total » row (sum or count)"),
        Key("row_totals", bool, default=False, help="a « Total » column, at the right"),
        Key("heatmap", bool, default=False, help="cells colored by their value"),
        Key("note", help="a line under the table"),
        Key("stub", bool, default=True, help="the first column as row headers"),
        Table("columns", values=dict, help="per column : format, decimals"),
        Table("options", values=object, help="given as is to great_tables tab_options"),
    ),
    help="how the table is drawn (great_tables)",
)


def _totals_need_a_sum(data: dict) -> Optional[str]:
    table = data.get("table") if isinstance(data.get("table"), dict) else {}
    if (table.get("totals") or table.get("row_totals")) and data.get(
        "aggregation", "sum"
    ) not in ("sum", "count"):
        return "Totals need the aggregation 'sum' or 'count'"
    return None


PIVOT = Kind(
    "pivot",
    (
        VERSION_KEY,
        FROM,
        Key("rows", column=True, required=True),
        Key("columns", column=True, required=True),
        Key("measure", column=True, required=True),
        Key("aggregation", choices=AGGREGATIONS, default="sum"),
        Key("grain", choices=GRAINS, help="the dates of the rows grouped by month"),
        Key("limit", int, help="the rows shown (else the setting table_rows)"),
        COMPUTED,
        LABELS,
        TABLE,
    ),
    rules=(_totals_need_a_sum,),
)

KINDS = {kind.name: kind for kind in (CARD, GRAPH, PIVOT)}


# ---- validation -------------------------------------------------------------
def validate(data: dict, kind: str, fields: Optional[set[str]] = None) -> list[str]:
    """The messages of a version 2 definition (none : valid). `fields` : the columns
    of the dataset, to check the column keys (not checked without it)."""
    schema = KINDS.get(kind)
    if schema is None:
        return [f"Kind '{kind}' has no version {VERSION} syntax"]
    if data.get("version", VERSION) != VERSION:
        return [f"Unknown version {data['version']!r} (2, or none)"]
    messages = []
    computed = data.get("computed") if isinstance(data.get("computed"), dict) else {}
    columns = (set(fields) | set(computed)) if fields else set()
    _check_entries(schema.entries, data, kind, columns, messages)
    for rule in schema.rules:
        message = rule(data)
        if message:
            messages.append(message)
    for name, expression in computed.items():
        if isinstance(expression, str) and not DATE_DIFF_RE.match(expression):
            messages.append(f"Computed column '{name}' must be '<date> - <date>'")
    return messages


def _check_entries(entries, data: dict, section: str, columns, messages) -> None:
    known = {entry.name for entry in entries}
    for name in data:
        if name not in known:
            messages.append(f"Unknown key '{name}' in {section}")
    for entry in entries:
        value = data.get(entry.name)
        if isinstance(entry, Table):
            _check_table(entry, value, section, columns, messages)
            continue
        if value is None:
            if entry.required:
                messages.append(f"Missing key '{entry.name}' in {section}")
            continue
        if not isinstance(value, entry.type) or (
            entry.type is int and isinstance(value, bool)
        ):
            messages.append(
                f"Key '{entry.name}' in {section} must be a {entry.type.__name__}"
            )
        elif entry.choices and value not in entry.choices:
            allowed = ", ".join(entry.choices)
            messages.append(
                f"Key '{entry.name}' in {section} must be one of : {allowed}"
            )
        elif entry.column and columns and value.partition(".")[0] not in columns:
            messages.append(f"Field '{value}' in {section} not found")


def _check_table(table: Table, value, section: str, columns, messages) -> None:
    if value is None:
        return
    if table.shorthand is not None and isinstance(value, table.shorthand):
        return
    if not isinstance(value, dict):
        messages.append(f"Key '{table.name}' in {section} must be a table")
        return
    where = f"{section}.{table.name}"
    if table.values is not None:
        for name, item in value.items():
            if not isinstance(item, table.values):
                messages.append(
                    f"Key '{name}' in {where} must be a {table.values.__name__}"
                )
        return
    _check_entries(table.keys, value, where, columns, messages)
    if table.name == "table" and isinstance(value.get("columns"), dict):
        for name, cell in value["columns"].items():
            if isinstance(cell, dict):
                _check_entries(
                    CELL_FORMAT, cell, f"{where}.columns.{name}", (), messages
                )


# ---- loading ----------------------------------------------------------------
def load(text: str, kind: str) -> dict:
    """The definition of a tile (TOML)."""
    return tomllib.loads(text)
