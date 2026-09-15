"""Parquet storage of the dataframes extracted from Odoo.

Port of marimo-kpiten `DFStorage`, without the RPC calls inside: the app
layer is responsible for providing `allowed_fields` and `lang` when it
retrieves a dataframe.
"""

import json
import logging
import pathlib
from datetime import datetime, timezone
from typing import TypedDict

import polars as pl

from kpiten_core import env
from kpiten_core.dfnorm import Df

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
            else:
                selects.append(pl.col(c).cast(current[c].dtype, strict=False))
        elif c in new_df:
            selects.append(pl.col(c))  # new column : keep as extracted
        else:
            selects.append(pl.lit(None, dtype=current[c].dtype).alias(c))
    return new_df.select(selects), gained


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
        DATA_PATH/<db>/<table>.parquet, or DATA_PATH/<table>.parquet when no
        database is scoped.
        """
        db = env.active_db()
        if db:
            return f"{env.data_path}/{db}"
        return f"{env.data_path}"

    @staticmethod
    def _cols_last(df: pl.DataFrame) -> pl.DataFrame:
        """Move '_' columns then constant columns to the end."""
        constant = [c for c in df.columns if df[c].drop_nulls().n_unique() <= 1]
        underscore = [c for c in df.columns if c.endswith("_") and c not in constant]
        rest = [c for c in df.columns if c not in constant and not c.endswith("_")]
        return df.select([*rest, *underscore, *constant])

    @classmethod
    def _parquet_path(cls, table: str) -> str:
        return f"{cls._df_dir()}/{table}.{cls.parquet_file_ext}"

    @classmethod
    def _meta_path(cls, table: str) -> str:
        return f"{cls._parquet_path(table)}.meta.json"

    @classmethod
    def store_raw(
        cls, table: str, raw_vals: list[dict], metadata: dict, df: pl.DataFrame
    ):
        """Store the parquet file + json metadata beside it."""
        pathlib.Path(cls._df_dir() + "/").mkdir(exist_ok=True, parents=True)
        df = cls._cols_last(df)
        with _table_lock(table, cls._df_dir()):
            df.write_parquet(cls._parquet_path(table))
            cls.write_meta(table, {**metadata, "last_sync": _now_utc()})

    @classmethod
    def init_table(
        cls, table: str, raw_vals: list[dict], metadata: dict, df: pl.DataFrame
    ):
        """Create a table's parquet + fields metadata WITHOUT setting last_sync.

        Used by the progressive recent->oldest load : the table is considered
        partial until it leaves the completion queue, so `last_sync` is only
        set once the whole table has been pulled (see `touch_sync`).
        """
        pathlib.Path(cls._df_dir() + "/").mkdir(exist_ok=True, parents=True)
        df = cls._cols_last(df)
        with _table_lock(table, cls._df_dir()):
            df.write_parquet(cls._parquet_path(table))
            cls.write_meta(table, metadata)

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
    def touch_sync(cls, table: str):
        """Update last_sync without touching the fields metadata."""
        meta = cls.read_meta(table)
        meta["last_sync"] = _now_utc()
        cls.write_meta(table, meta)

    @classmethod
    def last_sync(cls, table: str) -> str | None:
        """Datetime (string) of the end of the last extraction of this table."""
        return cls.read_meta(table).get("last_sync")

    @classmethod
    def table_exists(cls, table: str) -> bool:
        """Whether the table's parquet file has been written."""
        return pathlib.Path(cls._parquet_path(table)).exists()

    # ---- resumable sync state ------------------------------------------
    # A full table extract can be interrupted (RPC timeout). We persist a
    # per-table progress marker in the meta.json so the next sync resumes at
    # the same `offset` instead of restarting from scratch.

    @classmethod
    def get_sync_state(cls, table: str) -> dict | None:
        """Return the in-progress extraction marker for a table, or None."""
        return cls.read_meta(table).get("sync_state")

    @classmethod
    def set_sync_state(cls, table: str, state: dict):
        """Persist the extraction progress (model, offset, started_at)."""
        meta = cls.read_meta(table)
        meta["sync_state"] = {**state, "started_at": _now_utc()}
        cls.write_meta(table, meta)

    @classmethod
    def clear_sync_state(cls, table: str):
        """Drop the extraction progress marker (table fully synced)."""
        meta = cls.read_meta(table)
        if "sync_state" in meta:
            del meta["sync_state"]
            cls.write_meta(table, meta)

    # ---- progressive load state (recent->oldest) -----------------------
    # On a fresh db, tables are pulled by priority (panel first) and by
    # decreasing create_date. A global `prog` marker in `prog.json` keeps the
    # completion queue so background passes resume across app restarts.

    @classmethod
    def _prog_path(cls) -> str:
        return f"{cls._df_dir()}/prog.json"

    @classmethod
    def get_prog(cls) -> dict:
        """Completion queue state, or an empty dict when nothing is pending."""
        try:
            return json.loads(pathlib.Path(cls._prog_path()).read_text())
        except FileNotFoundError:
            return {}

    @classmethod
    def set_prog(cls, state: dict):
        """Persist the completion queue state."""
        pathlib.Path(cls._df_dir() + "/").mkdir(exist_ok=True, parents=True)
        pathlib.Path(cls._prog_path()).write_text(json.dumps(state))

    @classmethod
    def clear_prog(cls):
        """Drop the completion queue (all tables fully loaded)."""
        pathlib.Path(cls._df_dir() + "/").mkdir(exist_ok=True, parents=True)
        pathlib.Path(cls._prog_path()).write_text("{}")

    @classmethod
    def partial_tables(cls) -> set[str]:
        """Models still being pulled by the progressive load (partial parquet)."""
        prog = cls.get_prog()
        tables = set(prog.get("order", []))
        current = prog.get("current")
        if current and current.get("model"):
            tables.add(current["model"])
        return tables

    @classmethod
    def append_records(cls, table: str, raw_vals: list[dict]) -> pl.DataFrame:
        """Upsert rows in the stored parquet (delta-sync).

        The normalization (Df) is applied only to the new/updated rows, then
        they replace the matching `id` in the existing dataframe. New columns
        brought by the delta (new Odoo fields) are added to the parquet schema,
        with NULL on the already-stored rows.
        """
        new_df = Df.from_raw(table, raw_vals, cls.read_meta(table)).get_df()
        with _table_lock(table, cls._df_dir()):
            try:
                current = pl.read_parquet(cls._parquet_path(table))
            except FileNotFoundError:
                current = None
            if current is None or current.height == 0:
                df = new_df
            else:
                new_df, gained = _merge_schema(new_df, current)
                ids = new_df["id"].to_list()
                keep = current.filter(~pl.col("id").is_in(ids))
                # align the existing rows to the widened schema (new cols = NULL)
                if gained:
                    keep = keep.with_columns(
                        [pl.lit(None, dtype=new_df[c].dtype).alias(c) for c in gained]
                    )
                df = pl.concat([keep, new_df], how="vertical_relaxed")
            df = cls._cols_last(df)
            df.write_parquet(cls._parquet_path(table))
            return df

    @classmethod
    def delete_records(cls, table: str, res_ids: list[int]) -> pl.DataFrame | None:
        """Drop deleted-record rows (from auditlog unlink logs) and rewrite the parquet."""
        if not res_ids:
            return None
        with _table_lock(table, cls._df_dir()):
            try:
                current = pl.read_parquet(cls._parquet_path(table))
            except FileNotFoundError:
                return None
            df = current.filter(~pl.col("id").is_in(res_ids))
            if df.height != current.height:
                df.write_parquet(cls._parquet_path(table))
            return df

    @classmethod
    def retrieve_df(
        cls,
        table: str,
        allowed_fields: list[str] | None = None,
        lang: str | None = None,
    ) -> DF_META | None:
        """Read a stored dataframe.

        - filter the columns by `allowed_fields` (ACL per user, from the
          backend) when provided
        - de-structure translatable struct columns by user `lang`
        """
        try:
            df = pl.read_parquet(cls._parquet_path(table))
        except FileNotFoundError:
            raise Exception(f"No such table was stored : {table}")
        if allowed_fields is not None:
            found = [c for c in df.columns if cls._column_ok(c, allowed_fields)]
            df = df.select(found)
        struct_cols = [col for col, dt in zip(df.columns, df.dtypes) if dt == pl.Struct]
        if lang:
            df = df.with_columns(
                [pl.col(col).struct.field(lang).alias(col) for col in struct_cols]
            )
        return {"table": table, "df": df}

    @staticmethod
    def _column_ok(col: str, allowed: list[str]) -> bool:
        if _is_forbidden_column(col):
            return False
        # external columns (dot paths / m2o id cols) are always kept
        return col in allowed or _is_external_column(col)

    @classmethod
    def list_table_names(cls) -> list[str]:
        df_dir = pathlib.Path(cls._df_dir())
        if not df_dir.exists():
            return []
        return [
            f.stem for f in df_dir.iterdir() if f.suffix == f".{cls.parquet_file_ext}"
        ]
