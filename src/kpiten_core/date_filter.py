"""Generic date-range helper for dashboard global filters."""

import datetime

import polars as pl


def last_year_bounds(today: datetime.date) -> dict[str, datetime.date]:
    ly = today.year - 1
    return {
        "LY_first_day": datetime.date(ly, 1, 1),
        "LY_last_day": datetime.date(ly, 12, 31),
    }


def last_days(today: datetime.date, days: int) -> tuple[datetime.date, datetime.date]:
    """The `days` days ending today, today included : Odoo's relative periods
    (`getRelativeDateDomain`, "Last 30 Days" is 30 days, not one month)."""
    return today - datetime.timedelta(days=days - 1), today


# option -> number of days, the periods of an Odoo dashboard filter (7, 30, 90, 180
# and 365 days) and the old names that are still understood
DAYS_OF_OPTION = {
    "last 7 days": 7,
    "last week": 7,
    "last 30 days": 30,
    "last 90 days": 90,
    "last 180 days": 180,
    "last 6 months": 180,
    "last 365 days": 365,
    "last 1 year": 365,
    "last 5 years": 365 * 5,
}


def bounds_for_option(option: str | None) -> tuple[datetime.date, datetime.date] | None:
    """Start and end dates implied by a predefined period option."""
    if not option:
        return None
    today = datetime.date.today()
    if option == "today only":
        return today, today
    if option in DAYS_OF_OPTION:
        return last_days(today, DAYS_OF_OPTION[option])
    if option == "year to date":
        return datetime.date(today.year, 1, 1), today
    if option == "last year":
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
