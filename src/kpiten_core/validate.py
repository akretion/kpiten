"""Structural validation of KPI tile definitions (framework agnostic).

Each tile `definition` is TOML describing a `kind` (card / graph / pivot /
union). A definition with `version = 2` is checked by `spec` (the declarative schema
of the version 2) ; the rules below are the ones of the version 1. This module checks the loaded dict against the expected structure
derived from `tiles.py` (keys, types, enums, required fields) and returns a
list of human readable messages instead of raising.

It never touches Odoo : the caller may pass the set of valid column names
(`fields`) to also check that referenced columns exist. Without it, only the
structure is validated.
"""

import re
import tomllib
from typing import Any, Optional

from kpiten_core import spec

AGGREGATIONS = {"sum", "count", "mean", "none"}
CARD_AGGREGATIONS = {"count", "sum", "mean", "median", "min", "max"}
GRAPH_TYPES = {"bar", "point", "area"}
DERIVE_RE = re.compile(r"^\s*([\w.]+)\s*-\s*([\w.]+)\s*$")


def validate(
    definition: dict[str, Any],
    kind: str,
    fields: Optional[set[str]] = None,
) -> list[str]:
    """Return a list of validation messages for a loaded TOML definition.

    `definition` is the parsed TOML (dict). `fields` is an optional set of
    valid column names used to check that referenced columns exist.
    """
    if definition.get("version") is not None:
        if kind == "union":
            return ["The union has no version 2 syntax yet : remove 'version'"]
        if definition["version"] != spec.VERSION:
            return [f"Unknown version {definition['version']!r} (2, or none for 1)"]
        return spec.validate(definition, kind, fields)
    fields = fields or set()
    check = _Check(fields)
    if kind == "card":
        _card(check, definition)
    elif kind == "graph":
        _graph(check, definition)
    elif kind == "pivot":
        _pivot(check, definition)
    elif kind == "union":
        _union(check, definition)
    else:
        check.msg(f"Unknown kind '{kind}'")
    return check.messages


def validate_toml(
    text: str,
    kind: str,
    fields: Optional[set[str]] = None,
) -> list[str]:
    """Parse a TOML `text` and validate it for `kind`.

    Raises `tomllib.TOMLDecodeError` on a malformed TOML, otherwise returns
    the structural messages.
    """
    return validate(tomllib.loads(text), kind, fields)


class _Check:
    """Collector of validation messages with small helpers."""

    def __init__(self, fields: set[str]):
        self.fields = fields
        self.messages: list[str] = []

    def msg(self, message: str) -> None:
        self.messages.append(message)

    def has_fields(self) -> bool:
        return bool(self.fields)

    def expect_keys(self, data: dict, section: str, keys: set[str]) -> None:
        for key in data:
            if key not in keys:
                self.msg(f"Unknown key '{key}' in {section}")

    def expect_type(self, data: dict, key: str, section: str, expected: type) -> None:
        if key in data and not isinstance(data[key], expected):
            self.msg(f"Key '{key}' in {section} must be {expected.__name__}")

    def expect_str(self, data: dict, key: str, section: str) -> None:
        self.expect_type(data, key, section, str)

    def expect_bool(self, data: dict, key: str, section: str) -> None:
        self.expect_type(data, key, section, bool)

    def expect_enum(self, data: dict, key: str, section: str, allowed: set) -> None:
        if key in data and data[key] not in allowed:
            self.msg(f"Key '{key}' in {section} must be one of {sorted(allowed)}")

    def check_column(self, value: str, section: str) -> None:
        """Check a referenced column exists (first dotted segment)."""
        if not self.has_fields():
            return
        root = value.partition(".")[0]
        if root not in self.fields:
            self.msg(f"Field '{value}' in {section} not found")


def _card(check: _Check, data: dict) -> None:
    section = "card"
    check.expect_keys(
        data,
        section,
        {
            "where",
            "from",
            "aggregation",
            "measure",
            "unit",
            "decimals",
            "derive",
            "ignore_period",
            "compare",
            "good",
            "best",
            "detail",
            "detail_label",
        },
    )
    for key in ("where", "from", "measure", "unit"):
        check.expect_str(data, key, section)
    check.expect_bool(data, "ignore_period", section)
    check.expect_bool(data, "compare", section)
    check.expect_enum(data, "good", section, {"up", "down"})
    for key in ("best", "detail", "detail_label"):
        check.expect_str(data, key, section)
    if data.get("best"):
        if not data.get("measure"):
            check.msg("Card 'best' needs a 'measure' to rank the groups")
        for key in ("best", "detail"):
            if isinstance(data.get(key), str):
                check.check_column(data[key], section)
    check.expect_enum(data, "aggregation", section, CARD_AGGREGATIONS)
    check.expect_type(data, "decimals", section, int)
    aggregation = data.get("aggregation", "count")
    derive = data.get("derive", {})
    if not isinstance(derive, dict):
        check.msg("Key 'derive' in card must be a table")
        derive = {}
    if aggregation != "count" and not data.get("measure"):
        check.msg(f"Aggregation '{aggregation}' in card needs a 'measure'")
    for name, expression in derive.items():
        if not isinstance(expression, str) or not DERIVE_RE.match(expression):
            check.msg(f"Derived column '{name}' must be '<date> - <date>'")
    if data.get("measure") and data["measure"] not in derive:
        check.check_column(data["measure"], section)


def _graph(check: _Check, data: dict) -> None:
    section = "graph"
    check.expect_keys(
        data,
        section,
        {"graph_type", "from", "x", "y", "where", "monthly", "others"},
    )
    check.expect_enum(data, "graph_type", section, GRAPH_TYPES)
    check.expect_str(data, "from", section)
    check.expect_str(data, "where", section)
    check.expect_bool(data, "monthly", section)
    check.expect_bool(data, "others", section)
    if "x" not in data:
        check.msg("Missing key 'x' in graph")
    if "y" not in data:
        check.msg("Missing key 'y' in graph")
    for axis in ("x", "y"):
        if axis not in data:
            continue
        ax = data[axis]
        if not isinstance(ax, dict):
            check.msg(f"Key '{axis}' in graph must be a table")
            continue
        check.expect_keys(ax, f"graph.{axis}", {"name", "aggregation"})
        if "name" not in ax:
            check.msg(f"Missing key 'name' in graph.{axis}")
        else:
            check.expect_str(ax, "name", f"graph.{axis}")
            if isinstance(ax["name"], str):
                check.check_column(ax["name"], f"graph.{axis}")
        check.expect_enum(ax, "aggregation", f"graph.{axis}", AGGREGATIONS)


def _pivot(check: _Check, data: dict) -> None:
    section = "pivot"
    check.expect_keys(
        data, section, {"index", "column", "measure", "aggregation", "monthly", "from"}
    )
    for key in ("index", "column", "measure"):
        if key not in data:
            check.msg(f"Missing key '{key}' in pivot")
        else:
            check.expect_str(data, key, section)
            if isinstance(data[key], str):
                check.check_column(data[key], section)
    check.expect_enum(data, "aggregation", section, AGGREGATIONS)
    check.expect_bool(data, "monthly", section)
    check.expect_str(data, "from", section)


def _union(check: _Check, data: dict) -> None:
    section = "union"
    check.expect_keys(data, section, {"union_model", "mapping"})
    check.expect_str(data, "union_model", section)
    mapping = data.get("mapping")
    if mapping is None:
        check.msg("Missing key 'mapping' in union")
        return
    if not isinstance(mapping, dict):
        check.msg("Key 'mapping' in union must be a table")
        return
    for model, fields_map in mapping.items():
        msect = f"union.mapping.{model}"
        if not isinstance(fields_map, dict):
            check.msg(f"Key '{model}' in union.mapping must be a table")
            continue
        for source, target in fields_map.items():
            check.check_column(source, msect)
            if not isinstance(target, str):
                check.msg(f"Mapping '{source}' in {msect} must be a string")
