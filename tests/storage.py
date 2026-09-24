"""Helpers of the tests of the store : a table written whole, read back whole
(the app streams its blocks with `write_block` / `commit_full`, reads with `scan_df`).
"""

import polars as pl

from kpiten_core.store import ColumnOrder, DFStorage, _now_utc


def store_df(table: str, df: pl.DataFrame, metadata: dict | None = None):
    """Store a whole in-memory dataframe as blocks + json metadata."""
    started = _now_utc()
    blocks = DFStorage.split_blocks(df)
    for block, part in blocks:
        DFStorage.write_block(table, block, part)
    DFStorage.commit_full(
        table,
        metadata or {},
        {block for block, _ in blocks},
        ColumnOrder().update(df).order(),
        started,
    )


def read_df(table: str) -> pl.DataFrame:
    """The whole stored table, in memory."""
    return DFStorage.scan_df(table).collect()
