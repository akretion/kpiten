"""Dimension helpers for panel filters."""

import logging

import polars as pl

from kpiten_core import env

logger = logging.getLogger(__name__)


def dimension_values(dfs: list[pl.DataFrame], column: str) -> list[str]:
    """Distinct sorted values of a column across the tables that have it.

    A dimension with more than `env.dimension_max_values` values (a customer
    or an order number) would make a dropdown that freezes the browser : only
    the most frequent values are offered.
    """
    series = [
        df[column]
        for df in dfs
        if column in df.columns and not df[column].is_null().all()
    ]
    if not series:
        return []
    values = pl.concat(series)
    if values.n_unique() <= env.dimension_max_values:
        return values.unique().sort().to_list()
    logger.warning(
        "dimension %s has %s values : offering the %s most frequent",
        column,
        values.n_unique(),
        env.dimension_max_values,
    )
    top = values.drop_nulls().value_counts(sort=True).head(env.dimension_max_values)
    return top[column].sort().to_list()
