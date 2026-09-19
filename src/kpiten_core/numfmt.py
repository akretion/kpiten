"""Numbers as the dashboards show them (cards and tables).

Thousands are separated by a narrow no-break space ; the decimal mark is `,` by
default (`DECIMAL_MARK` in the environment changes it, e.g. `DECIMAL_MARK=.`).
"""

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
