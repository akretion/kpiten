"""Bulk many2one id -> display_name resolution for the direct-SQL extraction path.

`sql`/`view` extraction (see `loaders._extract_full_model_sql`) reads
many2one columns as bare foreign keys : Odoo's `kt_sql.build_select` no
longer joins/guesses a display column, since a SQL text-column guess can't
reproduce a model's own `display_name`/`name_get` override. That name is
resolved here instead, turned into the same `[id, name]` pair the jsonrpc
path returns, so `Df.split_many2one_result` normalizes both paths
identically.

Resolved names are cached per (db, comodel) for the life of the process : one
extraction run touches the same partners/users/products across most
datasets, so caching turns a per-model resolution into a handful of RPC
calls total instead of one per row.
"""

import logging
from typing import TYPE_CHECKING

import polars as pl

from kpiten_core import env

if TYPE_CHECKING:
    from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)

# (db, comodel) -> {id: display_name}
_cache: dict[tuple[str, str], dict[int, str]] = {}


def clear_cache() -> None:
    """Drop every cached display name (tests, or a long-lived worker)."""
    _cache.clear()


def _resolve(backend: "Backend", comodel: str, ids: set[int]) -> dict[int, str]:
    bucket = _cache.setdefault((env.active_db() or "", comodel), {})
    missing = ids - bucket.keys()
    if missing:
        logger.info("resolving %s display names for %s", len(missing), comodel)
        bucket.update(backend.get_display_names(comodel, sorted(missing)))
    return bucket


def inject_display_names(
    backend: "Backend", df: pl.DataFrame, fields: dict | None
) -> pl.DataFrame:
    """Turn raw many2one id columns of `df` into `[id, display_name]` pairs.

    Only columns still holding a bare integer id are touched (the direct-SQL
    / view path) ; a column already shaped as `[id, name]` (jsonrpc path) or
    fully null (no id to resolve) is left untouched for `Df` to normalize.
    """
    m2o_fields = {
        fname: spec["rel"]
        for fname, spec in (fields or {}).items()
        if isinstance(spec, dict) and spec.get("type") == "many2one" and spec.get("rel")
    }
    updates = {}
    for fname, comodel in m2o_fields.items():
        if fname not in df.columns or df.schema[fname] not in (pl.Int64, pl.Int32):
            continue
        ids = set(df[fname].drop_nulls().to_list())
        names = _resolve(backend, comodel, ids) if ids else {}
        updates[fname] = (
            pl.when(pl.col(fname).is_null())
            .then(None)
            .otherwise(
                pl.concat_list(
                    [
                        pl.col(fname).cast(pl.Utf8),
                        pl.col(fname).replace_strict(
                            names, default=None, return_dtype=pl.Utf8
                        ),
                    ]
                )
            )
        )
    if not updates:
        return df
    return df.with_columns(**updates)
