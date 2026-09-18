"""Dimension helpers for panel filters."""

import logging

import polars as pl

from kpiten_core import env

logger = logging.getLogger(__name__)


def dimension_values(
    frames: list[pl.DataFrame | pl.LazyFrame], column: str
) -> list[str]:
    """Distinct sorted values of a column across the tables that have it.

    Only that column is read. A dimension with more than
    `env.dimension_max_values` values (a customer, an order number) would make
    a dropdown that freezes the browser : only the most frequent are offered.
    """
    counts = [
        frame.lazy().select(pl.col(column)).drop_nulls().group_by(column).len()
        for frame in frames
        if column in frame.collect_schema()
    ]
    if not counts:
        return []
    top = (
        pl.concat(counts, how="vertical_relaxed")
        .group_by(column)
        .agg(pl.col("len").sum())
        .sort("len", descending=True)
        .head(env.dimension_max_values + 1)
        .collect(engine="streaming")
    )
    if top.height > env.dimension_max_values:
        logger.warning(
            "dimension %s has more than %s values : offering the most frequent",
            column,
            env.dimension_max_values,
        )
        top = top.head(env.dimension_max_values)
    return top[column].sort().to_list()
