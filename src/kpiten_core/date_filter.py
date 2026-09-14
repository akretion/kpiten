"""Generic date-range helper for dashboard global filters."""

import datetime

import polars as pl


def last_year_bounds(today: datetime.date) -> dict[str, datetime.date]:
    ly = today.year - 1
    return {
        "LY_first_day": datetime.date(ly, 1, 1),
        "LY_last_day": datetime.date(ly, 12, 31),
    }


def bounds_for_option(option: str | None) -> tuple[datetime.date, datetime.date] | None:
    """Start and end dates implied by a predefined period option."""
    from datetime import date, timedelta

    if not option:
        return None
    today = date.today()
    match option:
        case "today only":
            return today, today
        case "last week":
            return today - timedelta(days=7), today
        case "last 30 days":
            return today - timedelta(days=30), today
        case "last 90 days":
            return today - timedelta(days=90), today
        case "last 6 months":
            return today - timedelta(days=31 * 6), today
        case "last 1 year":
            return today - timedelta(days=365), today
        case "last 5 years":
            return today - timedelta(days=365 * 5), today
        case "last year":
            bounds = last_year_bounds(today)
            return bounds["LY_first_day"], bounds["LY_last_day"]
    return None


def process_dt_predicate(
    range_value: tuple[datetime.date, datetime.date] | None, column: str
) -> list[pl.Expr]:
    """Predicates restricting `column` to the given date range."""
    if not range_value:
        return []
    start, end = range_value
    return [pl.col(column) >= start, pl.col(column) <= end]
