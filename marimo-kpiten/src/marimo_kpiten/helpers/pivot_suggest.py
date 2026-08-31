import polars as pl

from marimo_kpiten.helpers.graph_suggest import classify_columns

_AGGREGATIONS = ["sum", "mean", "count", "min", "max"]


def pivot_roles(df: pl.DataFrame) -> dict[str, list[str]]:
    """Split columns into pivot roles: date, dimension (index/column), measure."""
    roles = classify_columns(df)
    return {
        "date": roles["date"],
        "dimension": roles["dimension"],
        "measure": roles["measure"],
    }


def suggest_pivot(df: pl.DataFrame) -> dict[str, str | None]:
    """Return sensible defaults: index=date, column=dimension, measure=measure."""
    roles = pivot_roles(df)
    index = (roles["date"] or roles["dimension"] or [None])[0]
    column = (roles["dimension"] or roles["date"] or [None])[0]
    if column == index:
        column = None
    measure = (roles["measure"] or [None])[0]
    return {"index": index, "column": column, "measure": measure}


def is_date(df: pl.DataFrame, column: str | None) -> bool:
    if not column or column not in df.columns:
        return False
    return df[column].dtype in (pl.Date, pl.Datetime)


def apply_monthly(df: pl.DataFrame, column: str) -> pl.DataFrame:
    """Truncate a date/datetime column to the month."""
    return df.with_columns(pl.col(column).dt.truncate("1mo"))
