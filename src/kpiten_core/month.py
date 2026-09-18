"""Pivot helpers (marimo-kpiten `pivot_suggest` port)."""

import polars as pl


def is_date(df: pl.DataFrame | pl.LazyFrame, column: str | None) -> bool:
    if not column:
        return False
    schema = df.collect_schema()
    return column in schema and schema[column] in (pl.Date, pl.Datetime)


def apply_monthly(
    df: pl.DataFrame | pl.LazyFrame, column: str
) -> pl.DataFrame | pl.LazyFrame:
    """Truncate a date/datetime column to the month."""
    return df.with_columns(pl.col(column).dt.truncate("1mo"))
