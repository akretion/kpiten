"""Numbers as the dashboards show them (cards and tables).

Thousands are separated by a narrow no-break space ; the decimal mark is `,` by
default (`DECIMAL_MARK` in the environment changes it, e.g. `DECIMAL_MARK=.`).
"""

from kpiten_core import env

THOUSANDS = "\u202f"  # narrow no-break space


def decimal_mark() -> str:
    return env.get("DECIMAL_MARK", ",")


def format_number(value, decimals: int = 0) -> str:
    """`4542884798.35` -> `4 542 884 798,35` (2 decimals)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", THOUSANDS).replace(".", decimal_mark())
