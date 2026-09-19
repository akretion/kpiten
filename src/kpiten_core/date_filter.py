"""Generic date-range helper for dashboard global filters."""

import datetime
import re

import polars as pl

from kpiten_core import config


def last_year_bounds(today: datetime.date) -> dict[str, datetime.date]:
    ly = today.year - 1
    return {
        "LY_first_day": datetime.date(ly, 1, 1),
        "LY_last_day": datetime.date(ly, 12, 31),
    }


def month_bounds(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    """First and last day of a calendar month."""
    first = datetime.date(year, month, 1)
    following = datetime.date(year + (month == 12), month % 12 + 1, 1)
    return first, following - datetime.timedelta(days=1)


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


def bounds_for_option(
    option: str | None, today: datetime.date | None = None
) -> tuple[datetime.date, datetime.date] | None:
    """Start and end dates implied by a predefined period option."""
    if not option:
        return None
    today = today or datetime.date.today()
    if option == "today only":
        return today, today
    if option in DAYS_OF_OPTION:
        return last_days(today, DAYS_OF_OPTION[option])
    calendar = re.fullmatch(r"(\d{4})(?:-(\d{2}))?", option)
    if calendar:  # "2025" : the calendar year, "2025-08" : the calendar month
        year, month = int(calendar[1]), int(calendar[2] or 0)
        if not month:
            return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
        return month_bounds(year, month)
    # the fiscal year of `kt.config` (starts on January 1st unless Odoo says otherwise)
    if option == "year to date":
        return config.fiscal_year_start(today), today
    if option == "last year":
        start = config.fiscal_year_start(today)
        return start.replace(year=start.year - 1), start - datetime.timedelta(days=1)
    return None


def process_dt_predicate(
    range_value: tuple[datetime.date, datetime.date] | None, column: str
) -> list[pl.Expr]:
    """Predicates restricting `column` to the given date range."""
    if not range_value:
        return []
    start, end = range_value
    return [pl.col(column) >= start, pl.col(column) <= end]
