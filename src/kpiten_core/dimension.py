"""Dimension helpers for panel filters."""

import polars as pl

MAX_DISTINCT = 50
MIN_DISTINCT = 2


def dimension_values(dfs: list[pl.DataFrame], column: str) -> list[str]:
    """Distinct sorted values of a column across the tables that have it."""
    series = [
        df[column]
        for df in dfs
        if column in df.columns and not df[column].is_null().all()
    ]
    if not series:
        return []
    return pl.concat(series).unique().sort().to_list()
