import datetime

import polars as pl

from marimo_kpiten.services.RPC import RPC
from marimo_kpiten.services.file_state import FileState

TIME_COLUMN = "create_date"


def last_year_bounds(today: datetime.date) -> dict[str, datetime.date]:
    ly = today.year - 1
    return {
        "LY_first_day": datetime.date(ly, 1, 1),
        "LY_last_day": datetime.date(ly, 12, 31),
    }


def bounds_for_option(
    option: str | None,
) -> tuple[datetime.date, datetime.date] | None:
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


def period_bounds(
    option: list[str] | None,
    range_value: tuple[datetime.date, datetime.date] | None = None,
) -> tuple[datetime.date, datetime.date] | None:
    """Effective start/end dates: the period when selected, else the custom range."""
    if option:
        return bounds_for_option(option[0])
    if range_value:
        return range_value
    return None


def user_lang() -> str:
    """Language of the logged Odoo user."""
    uid = FileState.retrieve_state("user_id")
    if not uid:
        return "en_US"
    try:
        return RPC().env["res.users"].browse(int(uid)).lang
    except Exception:
        return "en_US"


def _date_format(lang: str) -> str:
    formats = {
        "fr": "%d/%m/%Y",
        "en": "%m/%d/%Y",
        "de": "%d.%m.%Y",
    }
    for prefix, fmt in formats.items():
        if lang.lower().startswith(prefix):
            return fmt
    return "%Y-%m-%d"


def format_period(start: datetime.date, end: datetime.date, lang: str) -> str:
    fmt = _date_format(lang)
    return f"{start.strftime(fmt)} → {end.strftime(fmt)}"


def process_dt_predicate(
    option: list[str] | None,
    range_value: tuple[datetime.date, datetime.date] | None = None,
):
    bounds = period_bounds(option, range_value)
    if not bounds:
        return []
    start, end = bounds
    return [pl.col(TIME_COLUMN) >= start, pl.col(TIME_COLUMN) <= end]
