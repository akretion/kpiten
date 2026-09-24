"""Structural validation of KPI tile definitions (framework agnostic).

Each tile `definition` is TOML describing a `kind`. The card, the graph and the pivot
are checked by `spec` (the declarative schema of the syntax version 2) ; the union keeps
its own syntax, checked here. Returns human readable messages instead of raising.

It never touches Odoo : the caller may pass the set of valid column names
(`fields`) to also check that referenced columns exist. Without it, only the
structure is validated.
"""

import tomllib
from typing import Any, Optional

from kpiten_core import spec


def validate(
    definition: dict[str, Any],
    kind: str,
    fields: Optional[set[str]] = None,
) -> list[str]:
    """Return a list of validation messages for a loaded TOML definition.

    `definition` is the parsed TOML (dict). `fields` is an optional set of
    valid column names used to check that referenced columns exist.
    """
    if kind == "union":  # its own syntax, the one before the version 2
        if definition.get("version") is not None:
            return ["The union has no version 2 syntax yet : remove 'version'"]
        check = _Check(fields or set())
        _union(check, definition)
        return check.messages
    if kind in spec.KINDS:
        return spec.validate(definition, kind, fields)
    return [f"Unknown kind '{kind}'"]


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

    def check_column(self, value: str, section: str) -> None:
        """Check a referenced column exists (first dotted segment)."""
        if not self.has_fields():
            return
        root = value.partition(".")[0]
        if root not in self.fields:
            self.msg(f"Field '{value}' in {section} not found")


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
