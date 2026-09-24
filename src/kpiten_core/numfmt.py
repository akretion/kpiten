"""Numbers as the dashboards show them (cards and tables).

Thousands are separated by a narrow no-break space ; the decimal mark is `,` by
default (`DECIMAL_MARK` in the environment changes it, e.g. `DECIMAL_MARK=.`).
"""

import re

import polars as pl

from kpiten_core import config, env

THOUSANDS = "\u202f"  # narrow no-break space


def decimal_mark() -> str:
    """The format chosen in `kt.config`, else `DECIMAL_MARK`, else a comma."""
    return config.number_separators()[1] or env.get("DECIMAL_MARK", ",")


def thousands_separator() -> str:
    return config.number_separators()[0] or THOUSANDS


def format_number(value, decimals: int = 0) -> str:
    """`4542884798.35` -> `4 542 884 798,35` (2 decimals)."""
    text = f"{value:,.{decimals}f}"
    # both marks at once : a comma may become the thousands and the point the comma
    marks = str.maketrans({",": thousands_separator(), ".": decimal_mark()})
    return text.translate(marks)


def format_quantity(value) -> str:
    """A decimal of a table : whole, except below 10 where the decimals still tell
    something (`3116.4` -> `3 116`, `6.75` -> `6,75`, `0.42` -> `0,42`). The limit
    and the digits are the ones of `kt.config` (see `config.quantity_digits`)."""
    return format_number(value, config.quantity_digits(value))


FORMATS = ("number", "integer", "currency", "percent")


def with_currency(text: str) -> str:
    """`text` with the symbol of the company currency (`kt.config`), before or after
    it as Odoo does ; unchanged without a symbol."""
    currency = config.CONFIG.get("currency") or {}
    symbol = currency.get("symbol")
    if not symbol:
        return text
    if currency.get("position") == "before":
        return f"{symbol}{text}"
    return f"{text} {symbol}"


def format_value(value, fmt: str = "number", decimals: int = 0) -> str:
    """A cell of a table in a format of `[table]` : number, integer, currency (the
    company's) or percent (a ratio : 0.12 -> 12 %)."""
    if value is None:
        return ""
    if fmt == "integer":
        return format_number(value, 0)
    if fmt == "percent":
        return f"{format_number(value * 100, decimals)} %"
    text = format_number(value, decimals)
    return with_currency(text) if fmt == "currency" else text


# numbers that are not quantities : ids and calendar parts stay as they are
NOT_A_QUANTITY_RE = re.compile(r"(?i)(^|[\s._-])(id|year|quarter|month|week|day)s?$")


def number_columns(df: pl.DataFrame) -> tuple[list[str], list[str]]:
    """The (integer, decimal) columns of quantities : those are formatted."""
    integers, decimals = [], []
    for name, dtype in df.schema.items():
        if dtype == pl.Boolean or not dtype.is_numeric():
            continue
        if NOT_A_QUANTITY_RE.search(name):
            continue
        (integers if dtype.is_integer() else decimals).append(name)
    return integers, decimals
