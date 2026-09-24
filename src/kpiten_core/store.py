"""Parquet storage of the dataframes extracted from Odoo.

Port of marimo-kpiten `DFStorage`, without the RPC calls inside: the app
layer is responsible for providing `allowed_fields` and `lang` when it
retrieves a dataframe.

Layout, per Odoo database :

    <db>/<table>/<block>.parquet    the records whose id // PARTITION_SIZE is
                                    <block> (000000.parquet, 000001.parquet...)
    <db>/<table>.parquet.meta.json  fields metadata, last_sync, layout, columns
    <db>/<table>.parquet            legacy single file, still read until a full
                                    sync has migrated the table to blocks

A record always belongs to the same block (its id never changes), so a sync
writes a big table block after block with a bounded memory, and a delta or a
deletion only rewrites the few blocks it touches instead of the whole table.
Block files are only ever replaced atomically, never removed : the dashboards
hold lazy plans that reference them.
"""

import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import TypedDict

import polars as pl

from kpiten_core import env

logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _table_lock(table: str, df_dir: str):
    """Advisory file lock serializing parquet writes for a table.

    Two dashboard processes (shiny / nicegui) may target the same parquet
    dir ; the lock prevents them from corrupting a file on concurrent writes.
    """
    import fcntl
    import contextlib

    lock_path = pathlib.Path(df_dir) / f"{table}.lock"

    @contextlib.contextmanager
    def _lock():
        pathlib.Path(df_dir + "/").mkdir(exist_ok=True, parents=True)
        with open(lock_path, "w") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    return _lock()


def _is_text_dtype(dtype) -> bool:
    """Whether a polars dtype is a string/utf8 type."""
    return any(
        dtype == t
        for t in (pl.String, getattr(pl, "Utf8", None), getattr(pl, "Utf8View", None))
        if t is not None
    )


def _merge_schema(
    new_df: pl.DataFrame, current: pl.DataFrame
) -> tuple[pl.DataFrame, list[str]]:
    """Align a delta df to the stored parquet schema, adding new columns.

    Returns (aligned_new_df, gained_columns) where `gained_columns` are the
    columns present in `new_df` but missing from the stored parquet (i.e. new
    Odoo fields). The aligned df keeps the current column order and appends the
    new columns ; the relaxed concat then widens the parquet schema.
    """
    gained = [c for c in new_df.columns if c not in current.columns]
    union = [*current.columns, *gained]
    selects = []
    for c in union:
        if c in new_df and c in current:
            if _is_text_dtype(new_df[c].dtype) and not _is_text_dtype(current[c].dtype):
                selects.append(pl.col(c))  # keep the text dtype, avoid bad cast
            elif isinstance(new_df[c].dtype, pl.Decimal) and isinstance(
                current[c].dtype, pl.Decimal
            ):
                selects.append(pl.col(c))  # the relaxed concat keeps the wider scale
            else:
                selects.append(pl.col(c).cast(current[c].dtype, strict=False))
        elif c in new_df:
            selects.append(pl.col(c))  # new column : keep as extracted
        else:
            selects.append(pl.lit(None, dtype=current[c].dtype).alias(c))
    return new_df.select(selects), gained


def _lang_key(dtype: pl.Struct, lang: str) -> str:
    """Struct field holding a translatable column in `lang`.

    The struct only has the languages present in the data : when the user's
    language is absent, fall back on en_US, else on the first one, instead of
    failing the whole table.
    """
    names = [f.name for f in dtype.fields]
    if lang in names:
        return lang
    return "en_US" if "en_US" in names else names[0]


class ColumnOrder:
    """Display order of the columns of a whole table : the plain columns, then
    the `_` ones (many2one ids), then the constant ones.

    Fed block after block (`update`), it gives the order of the whole table
    without ever holding it : per column it only remembers the first two
    distinct values it saw, enough to know whether the column is constant.
    """

    def __init__(self):
        self._seen: dict[str, set] = {}

    def update(self, df: pl.DataFrame) -> "ColumnOrder":
        for col in df.columns:
            seen = self._seen.setdefault(col, set())
            if len(seen) > 1:
                continue
            try:
                seen.update(df[col].drop_nulls().unique().head(2).to_list())
            except TypeError:  # lists / structs are not hashable : not constant
                seen.update((0, 1))
        return self

    def order(self) -> list[str]:
        constant = [c for c, seen in self._seen.items() if len(seen) <= 1]
        underscore = [c for c in self._seen if c.endswith("_") and c not in constant]
        rest = [c for c in self._seen if c not in constant and not c.endswith("_")]
        return [*rest, *underscore, *constant]


class DF_META(TypedDict):
    table: str
    df: pl.DataFrame


def _is_forbidden_column(c: str) -> bool:
    return c in ("__last_update",) or c.startswith("__")


def _is_external_column(c: str) -> bool:
    return "." in c or c.endswith("_")


class DFStorage:
    parquet_file_ext = "parquet"

    @classmethod
    def _df_dir(cls) -> str:
        """Parquet dir : DATA_PATH/[db/] (scoping per odoo database).

        Files live directly in the data dir (no intermediate `parquet` subdir) :
        DATA_PATH/<db>/<table>/<block>.parquet, or DATA_PATH/<table>/... when no
        database is scoped.
        """
        db = env.active_db()
        if db:
            return f"{env.data_path}/{db}"
        return f"{env.data_path}"

    @classmethod
    def directory(cls) -> str:
        """The directory holding the tables of the scoped database."""
        return cls._df_dir()

    @classmethod
    def _legacy_path(cls, table: str) -> str:
        """The single parquet file of a table not migrated to blocks yet."""
        return f"{cls._df_dir()}/{table}.{cls.parquet_file_ext}"

    @classmethod
    def _table_dir(cls, table: str) -> str:
        return f"{cls._df_dir()}/{table}"

    @classmethod
    def _block_path(cls, table: str, block: int) -> str:
        return f"{cls._table_dir(table)}/{block:06d}.{cls.parquet_file_ext}"

    @classmethod
    def _meta_path(cls, table: str) -> str:
        return f"{cls._legacy_path(table)}.meta.json"

    @staticmethod
    def now() -> str:
        """Current UTC time, as stored in `last_sync`."""
        return _now_utc()

    @staticmethod
    def _atomic_write(path: str, df: pl.DataFrame):
        """Write a parquet atomically (tmp file + rename).

        The dashboards read the blocks lazily (`scan_df`), possibly while a
        sync is rewriting one : a reader must see the old or the new file,
        never a half written one. Callers hold the table lock.
        """
        pathlib.Path(path).parent.mkdir(exist_ok=True, parents=True)
        tmp = f"{path}.tmp"
        df.write_parquet(tmp)
        os.replace(tmp, path)

    @staticmethod
    def split_blocks(df: pl.DataFrame) -> list[tuple[int, pl.DataFrame]]:
        """The rows of `df` per id block, in block order (rows keep their order)."""
        keyed = df.with_columns(_block=pl.col("id") // env.partition_size)
        parts = keyed.partition_by("_block", as_dict=True, include_key=False)
        return sorted(
            ((key[0], part) for key, part in parts.items()), key=lambda b: b[0]
        )

    @classmethod
    def is_partitioned(cls, table: str) -> bool:
        """Whether the table is stored in blocks (else legacy file, or absent).

        Only set once a full extraction has completed : until then readers keep
        using the legacy file rather than a half written set of blocks.
        """
        return cls.read_meta(table).get("layout") == "partitioned"

    @classmethod
    def _blocks(cls, table: str) -> list[pathlib.Path]:
        return sorted(
            pathlib.Path(cls._table_dir(table)).glob(f"*.{cls.parquet_file_ext}")
        )

    @classmethod
    def write_block(cls, table: str, block: int, df: pl.DataFrame):
        """Replace one block with `df` (a full extraction writes them one by
        one as it streams the table)."""
        with _table_lock(table, cls._df_dir()):
            cls._atomic_write(cls._block_path(table, block), df.sort("id"))

    @classmethod
    def commit_full(
        cls,
        table: str,
        metadata: dict,
        written: set[int],
        columns: list[str],
        started: str,
    ):
        """Seal a full extraction whose blocks are all written.

        - blocks left over from a previous state (records deleted since, or a
          different PARTITION_SIZE) are emptied, not removed : a live plan may
          still reference the file
        - the table becomes readable as blocks (`layout`) and the legacy single
          file, if any, goes away
        - `last_sync` is the time the extraction STARTED : a record written
          while it ran is re-read by the next delta instead of being missed
        """
        with _table_lock(table, cls._df_dir()):
            keep = {pathlib.Path(cls._block_path(table, b)) for b in written}
            for path in cls._blocks(table):
                if path not in keep:
                    empty = pl.DataFrame(schema=pl.read_parquet_schema(path))
                    cls._atomic_write(str(path), empty)
            cls.write_meta(
                table,
                {
                    **metadata,
                    "last_sync": started,
                    "layout": "partitioned",
                    "columns": columns,
                },
            )
            pathlib.Path(cls._legacy_path(table)).unlink(missing_ok=True)

    @classmethod
    def write_meta(cls, table: str, metadata: dict):
        pathlib.Path(cls._df_dir() + "/").mkdir(exist_ok=True, parents=True)
        pathlib.Path(cls._meta_path(table)).write_text(json.dumps(metadata))

    @classmethod
    def read_meta(cls, table: str) -> dict:
        try:
            return json.loads(pathlib.Path(cls._meta_path(table)).read_text())
        except FileNotFoundError:
            return {}

    @classmethod
    def touch_sync(cls, table: str, at: str | None = None):
        """Update last_sync (default now) without touching the fields metadata."""
        meta = cls.read_meta(table)
        meta["last_sync"] = at or _now_utc()
        cls.write_meta(table, meta)

    @classmethod
    def last_sync(cls, table: str) -> str | None:
        """Datetime (string) of the start of the last extraction of this table."""
        return cls.read_meta(table).get("last_sync")

    @classmethod
    def table_exists(cls, table: str) -> bool:
        """Whether the table has been stored (as blocks, or legacy file)."""
        if cls.is_partitioned(table) and cls._blocks(table):
            return True
        return pathlib.Path(cls._legacy_path(table)).exists()

    @classmethod
    def _require_blocks(cls, table: str):
        if (
            not cls.is_partitioned(table)
            and pathlib.Path(cls._legacy_path(table)).exists()
        ):
            raise Exception(
                f"{table} is still stored as a single file : run a full sync to "
                "migrate it before applying deltas"
            )

    @classmethod
    def merge_df(
        cls,
        table: str,
        new_df: pl.DataFrame,
        columns: list[str] | None = None,
    ) -> int:
        """Upsert an already-normalized dataframe in the stored table (delta-sync).

        The rows in `new_df` replace the matching `id`. Only the blocks holding
        those ids are read and rewritten. New columns brought by the delta (new
        Odoo fields) are added to the schema of the blocks they reach, NULL on
        the already-stored rows ; the other blocks get them as NULL when read.
        Returns the number of rows written.
        """
        cls._require_blocks(table)
        gained_all: list[str] = []
        with _table_lock(table, cls._df_dir()):
            for block, part in cls.split_blocks(new_df):
                path = cls._block_path(table, block)
                try:
                    current = pl.read_parquet(path)
                except FileNotFoundError:
                    current = None
                if current is None or current.height == 0:
                    merged = part
                else:
                    part, gained = _merge_schema(part, current)
                    gained_all += [c for c in gained if c not in gained_all]
                    keep = current.filter(~pl.col("id").is_in(part["id"].to_list()))
                    # align the existing rows to the widened schema (new cols = NULL)
                    if gained:
                        keep = keep.with_columns(
                            [pl.lit(None, dtype=part[c].dtype).alias(c) for c in gained]
                        )
                    merged = pl.concat([keep, part], how="vertical_relaxed")
                cls._atomic_write(path, merged.sort("id"))
            meta = cls.read_meta(table)
            known = meta.get("columns") or []
            new_cols = [c for c in (columns or new_df.columns) if c not in known]
            meta.update(layout="partitioned", columns=[*known, *new_cols])
            cls.write_meta(table, meta)
        return new_df.height

    @classmethod
    def delete_records(cls, table: str, res_ids: list[int]) -> int:
        """Drop deleted records (ids from auditlog unlink logs) from the table.

        The block of an id is `id // PARTITION_SIZE` : only those blocks are
        read and rewritten. Returns the number of rows removed.
        """
        if not res_ids:
            return 0
        cls._require_blocks(table)
        by_block: dict[int, list[int]] = {}
        for res_id in res_ids:
            by_block.setdefault(res_id // env.partition_size, []).append(res_id)
        removed = 0
        with _table_lock(table, cls._df_dir()):
            for block, ids in by_block.items():
                path = cls._block_path(table, block)
                try:
                    current = pl.read_parquet(path)
                except FileNotFoundError:
                    continue
                df = current.filter(~pl.col("id").is_in(ids))
                if df.height != current.height:
                    cls._atomic_write(path, df)
                    removed += current.height - df.height
        return removed

    @classmethod
    def _scan_table(cls, table: str) -> pl.LazyFrame:
        """Lazy scan of the whole table, in the order of its meta `columns`.

        The blocks are unioned with a relaxed diagonal concat : each block was
        normalized on its own rows, so their column types can differ a little
        (a decimal scale, a column that is all null in one of them) and a
        block may lack a column another one has.
        """
        blocks = cls._blocks(table) if cls.is_partitioned(table) else []
        if blocks:
            scans = [pl.scan_parquet(str(path), glob=False) for path in blocks]
            lf = scans[0]
            if len(scans) > 1:
                lf = pl.concat(scans, how="diagonal_relaxed")
            order = cls.read_meta(table).get("columns") or []
            names = lf.collect_schema().names()
            wanted = [c for c in order if c in names] + [
                c for c in names if c not in order
            ]
            return lf if wanted == names else lf.select(wanted)
        legacy = cls._legacy_path(table)
        if not pathlib.Path(legacy).exists():
            raise Exception(f"No such table was stored : {table}")
        return pl.scan_parquet(legacy, glob=False)

    @classmethod
    def scan_df(
        cls,
        table: str,
        allowed_fields: list[str] | None = None,
        lang: str | None = None,
    ) -> pl.LazyFrame:
        """Lazily read a stored dataframe : nothing is loaded in memory here.

        The parquet is only read when a tile collects a result, and then only
        the columns and row groups that tile needs (projection / predicate
        pushdown) : a dashboard session holds a query plan, not the table.

        - filter the columns by `allowed_fields` (ACL per user, from the
          backend) when provided
        - de-structure translatable struct columns by user `lang`
        """
        lf = cls._scan_table(table)
        if allowed_fields is not None:
            found = [
                c
                for c in lf.collect_schema().names()
                if cls._column_ok(c, allowed_fields)
            ]
            lf = lf.select(found)
        if lang:
            lf = lf.with_columns(
                [
                    pl.col(col).struct.field(_lang_key(dtype, lang)).alias(col)
                    for col, dtype in lf.collect_schema().items()
                    if dtype == pl.Struct
                ]
            )
        return lf

    @staticmethod
    def _column_ok(col: str, allowed: list[str]) -> bool:
        if _is_forbidden_column(col):
            return False
        # external columns (dot paths / m2o id cols) are always kept
        return col in allowed or _is_external_column(col)

    @classmethod
    def list_table_names(cls) -> list[str]:
        """Tables stored as blocks (extraction completed) or as a legacy file."""
        df_dir = pathlib.Path(cls._df_dir())
        if not df_dir.exists():
            return []
        legacy = {
            f.stem for f in df_dir.iterdir() if f.suffix == f".{cls.parquet_file_ext}"
        }
        blocks = {
            d.name
            for d in df_dir.iterdir()
            if d.is_dir() and cls.is_partitioned(d.name)
        }
        return sorted(legacy | blocks)
