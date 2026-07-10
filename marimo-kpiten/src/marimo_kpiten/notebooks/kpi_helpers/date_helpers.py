import polars as pl
import marimo as mo


def process_dt_predicate(date_select: mo.ui.multiselect):
    from datetime import timedelta, datetime

    date_predicates: list[pl.Expr] = []
    time_column = (
        "create_date"  # create_date happens to have distinct values, better for testing
    )
    match date_select.value[0]:
        case "today only":
            date_predicates.append(pl.col(time_column) >= datetime.now())
        case "last week":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=7)
            )
        case "last 30 days":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=30)
            )
        case "last 90 days":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=90)
            )
        case "last 6 months":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=31 * 6)
            )
        case "last year":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=365)
            )
        case _:
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=30)
            )
    return (date_predicates,)
