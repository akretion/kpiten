import datetime
import logging

import marimo as mo
import polars as pl

logger = logging.getLogger(__name__)


def last_year_bounds(today: datetime.date) -> dict[str, datetime.date]:
    ly = today.year - 1
    return {
        "LY_first_day": datetime.date(ly, 1, 1),
        "LY_last_day": datetime.date(ly, 12, 31),
    }


def period_bounds(
    date_select: mo.ui.multiselect,
) -> tuple[datetime.date, datetime.date] | None:
    """Start and end dates implied by the selected period."""
    from datetime import date, timedelta

    today = date.today()
    match date_select.value[0]:
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


def process_dt_predicate(date_select: mo.ui.multiselect):
    from datetime import date, timedelta

    date_predicates: list[pl.Expr] = []
    time_column = (
        "create_date"  # create_date happens to have distinct values, better for testing
    )
    today = date.today()
    match date_select.value[0]:
        case "today only":
            date_predicates.append(pl.col(time_column) >= today)
        case "last week":
            date_predicates.append(pl.col(time_column) >= today - timedelta(days=7))
        case "last 30 days":
            date_predicates.append(pl.col(time_column) >= today - timedelta(days=30))
        case "last 90 days":
            date_predicates.append(pl.col(time_column) >= today - timedelta(days=90))
        case "last 6 months":
            date_predicates.append(
                pl.col(time_column) >= today - timedelta(days=31 * 6)
            )
        case "last 1 year":
            date_predicates.append(pl.col(time_column) >= today - timedelta(days=365))
        case "last 5 years":
            date_predicates.append(
                pl.col(time_column) >= today - timedelta(days=365 * 5)
            )
        case "last year":
            LY_info = last_year_bounds(today)
            logger.debug(LY_info)
            date_predicates.append(
                (pl.col(time_column) >= LY_info["LY_first_day"])
                & (pl.col(time_column) <= LY_info["LY_last_day"])
            )
        case _:
            date_predicates.append(pl.col(time_column) >= today - timedelta(days=30))
    return date_predicates
