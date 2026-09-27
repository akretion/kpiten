"""The filters of a panel (`kt.panel.filter_config`) : TOML.

    [date]
    field = ["date_order", "order_id.date_order"]

    [[dimensions]]
    name = "user_id"
    label = "Salesperson"

It was JSON before the module 1.20.0 : a JSON value (the data of an older module, a
paste) is written back as TOML (`normalize`).
"""

from __future__ import annotations

import json

from .compat import tomllib


def _value(value) -> str:
    """A TOML value : the few types a filter config holds."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # a TOML basic string
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):  # nested in a table : an inline table
        return "{" + ", ".join(f"{k} = {_value(v)}" for k, v in value.items()) + "}"
    raise ValueError(f"no TOML for {value!r}")


def _table(values: dict) -> list[str]:
    return [f"{key} = {_value(value)}" for key, value in values.items()]


def to_toml(config: dict) -> str:
    """The TOML of a filter config : its values, then a `[table]` per dict, a
    `[[table]]` per list of dicts."""
    lines = _table(
        {
            k: v
            for k, v in config.items()
            if not isinstance(v, dict) and not _is_tables(v)
        }
    )
    for key, value in config.items():
        if isinstance(value, dict):
            lines += ["", f"[{key}]", *_table(value)]
        elif _is_tables(value):
            for item in value:
                lines += ["", f"[[{key}]]", *_table(item)]
    text = "\n".join(lines).strip()
    return text + "\n" if text else ""


def _is_tables(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(isinstance(v, dict) for v in value)
    )


def normalize(text: str | None) -> str:
    """`text` in TOML : a JSON one converted, a TOML one as it is (empty : no
    filter)."""
    if not text or not text.strip():
        return ""
    if text.lstrip().startswith("{"):
        try:
            return to_toml(json.loads(text))
        except ValueError:  # not JSON : the constraint of the panel says why
            return text
    return text


def errors(config: dict) -> list[str]:
    """What is wrong in a filter config (its TOML read) : empty when it is valid."""
    found = []
    unknown = set(config) - {"date", "dimensions"}
    if unknown:
        found.append(f"unknown keys : {', '.join(sorted(unknown))} (date, dimensions)")
    date = config.get("date")
    if date is not None:
        field = date.get("field") if isinstance(date, dict) else None
        texts = field if isinstance(field, list) else [field]
        if not field or not all(isinstance(f, str) and f for f in texts):
            found.append(
                '[date] needs a field : field = "date_order" (or a list of fields)'
            )
    dimensions = config.get("dimensions", [])
    if not isinstance(dimensions, list) or not all(
        isinstance(d, dict) for d in dimensions
    ):
        found.append('the dimensions are tables : [[dimensions]] name = "user_id"')
    else:
        for i, dim in enumerate(dimensions, 1):
            if not isinstance(dim.get("name"), str) or not dim["name"]:
                found.append(f'dimension {i} needs a name : name = "user_id"')
            if "label" in dim and not isinstance(dim["label"], str):
                found.append(f"the label of dimension {i} is a text")
    return found


def parse(text: str | None) -> dict:
    """The dict of a filter config (TOML, or JSON of an older module)."""
    if not text or not text.strip():
        return {}
    if text.lstrip().startswith("{"):
        return json.loads(text)
    return tomllib.loads(text)
