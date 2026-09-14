"""Pivot helpers (marimo-kpiten `pivot_suggest` port)."""

import polars as pl


def is_date(df: pl.DataFrame, column: str | None) -> bool:
    if not column or column not in df.columns:
        return False
    return df[column].dtype in (pl.Date, pl.Datetime)


def apply_monthly(df: pl.DataFrame, column: str) -> pl.DataFrame:
    """Truncate a date/datetime column to the month."""
    return df.with_columns(pl.col(column).dt.truncate("1mo"))
