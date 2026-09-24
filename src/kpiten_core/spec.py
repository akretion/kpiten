"""The syntax of the kpi definitions, version 2 (see docs/kpi-syntaxe-v2.md).

One declarative schema per kind (`CARD`, `GRAPH`, `PIVOT`) : each key with its type,
its allowed values, its default and a help text. The same schema checks a definition
(`validate`), and will give the tooltips and the form of a tile builder.

A definition without `version = 2` is a version 1 one : `load` converts it (`upgrade`),
so the tiles only read version 2. The union stays in version 1 (other changes await it).

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
GRAPH_TYPES = ("bar", "point", "area")
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
        COMPUTED,
        LABELS,
    ),
)

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
        COMPUTED,
        LABELS,
    ),
)

KINDS = {kind.name: kind for kind in (CARD, GRAPH, PIVOT)}


# ---- validation -------------------------------------------------------------
def validate(data: dict, kind: str, fields: Optional[set[str]] = None) -> list[str]:
    """The messages of a version 2 definition (none : valid). `fields` : the columns
    of the dataset, to check the column keys (not checked without it)."""
    schema = KINDS.get(kind)
    if schema is None:
        return [f"Kind '{kind}' has no version {VERSION} syntax"]
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


# ---- version 1 -> version 2 -------------------------------------------------
def upgrade(data: dict, kind: str) -> dict:
    """A version 1 definition in version 2 (the union : unchanged). Raises
    `ValueError` for what version 2 cannot say."""
    if kind == "card":
        return _upgrade_card(data)
    if kind == "graph":
        return _upgrade_graph(data)
    if kind == "pivot":
        return _upgrade_pivot(data)
    return data


def _copy(data: dict, *names: str) -> dict:
    return {name: data[name] for name in names if name in data}


def _upgrade_card(data: dict) -> dict:
    new = {"version": VERSION}
    new.update(_copy(data, "where", "from", "measure", "aggregation"))
    if data.get("best"):
        new["by"] = data["best"]
    new.update(_copy(data, "unit", "decimals", "ignore_period"))
    if data.get("compare"):
        good = data.get("good", "up")
        new["compare"] = True if good == "up" else {"good": good}
    if data.get("detail"):
        new["detail"] = {"measure": data["detail"]}
        if data.get("detail_label"):
            new["detail"]["label"] = data["detail_label"]
    if data.get("derive"):
        new["computed"] = dict(data["derive"])
    return new


def _upgrade_graph(data: dict) -> dict:
    x, y = data.get("x") or {}, data.get("y") or {}
    if x.get("aggregation", "none") != "none":
        raise ValueError("graph : an aggregation on x has no version 2 syntax")
    new = {"version": VERSION, "type": data.get("graph_type", "bar")}
    new.update(_copy(data, "where", "from"))
    if "name" in x:
        new["by"] = x["name"]
    if data.get("monthly"):
        new["grain"] = "month"
    if "name" in y:
        new["measure"] = y["name"]
    new["aggregation"] = y.get("aggregation", "sum")
    if data.get("others"):
        new["others"] = True
    return new


def _upgrade_pivot(data: dict) -> dict:
    new = {"version": VERSION}
    new.update(_copy(data, "from"))
    if "index" in data:
        new["rows"] = data["index"]
    if "column" in data:
        new["columns"] = data["column"]
    new.update(_copy(data, "measure", "aggregation"))
    if data.get("monthly"):
        new["grain"] = "month"
    return new


# ---- loading ----------------------------------------------------------------
def is_v2(data: dict) -> bool:
    return data.get("version") == VERSION


def load(text: str, kind: str) -> dict:
    """The definition of a tile, in version 2 whatever it is written in (a union :
    as written)."""
    data = tomllib.loads(text)
    if kind == "union" or is_v2(data):
        return data
    return upgrade(data, kind)
