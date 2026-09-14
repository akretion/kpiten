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


def _align_schema(new_df: pl.DataFrame, current: pl.DataFrame) -> pl.DataFrame:
    """Order the delta columns as the stored parquet (missing -> null)."""
    selects = [
        (
            pl.col(c).cast(current[c].dtype, strict=False)
            if c in new_df.columns
            else pl.lit(None, dtype=current[c].dtype).alias(c)
        )
        for c in current.columns
    ]
    return new_df.select(selects)


class DF_META(TypedDict):
    table: str
    df: pl.DataFrame


def _is_forbidden_column(c: str) -> bool:
    return c in ("__last_update",) or c.startswith("__")


def _is_external_column(c: str) -> bool:
    return "." in c or c.endswith("_")


class DFStorage:
    df_data_dir_name = "parquet"
    parquet_file_ext = "parquet"

    @classmethod
    def _df_dir(cls) -> str:
        """Parquet dir : DATA_PATH/[db/]parquet (scoping per odoo database)."""
        if env.current_db:
            return f"{env.data_path}/{env.current_db}/{cls.df_data_dir_name}"
        return f"{env.data_path}/{cls.df_data_dir_name}"

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
        df.write_parquet(cls._parquet_path(table))
        cls.write_meta(table, {**metadata, "last_sync": _now_utc()})

    @classmethod
    def write_meta(cls, table: str, metadata: dict):
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
    def append_records(cls, table: str, raw_vals: list[dict]) -> pl.DataFrame:
        """Upsert rows in the stored parquet (delta-sync).

        The normalization (Df) is applied only to the new/updated rows, then
        they replace the matching `id` in the existing dataframe.
        """
        try:
            current = pl.read_parquet(cls._parquet_path(table))
        except FileNotFoundError:
            current = None
        new_df = Df.from_raw(table, raw_vals, cls.read_meta(table)).get_df()
        if current is None or current.height == 0:
            df = new_df
        else:
            new_df = _align_schema(new_df, current)
            ids = new_df["id"].to_list()
            keep = current.filter(~pl.col("id").is_in(ids))
            df = pl.concat([keep, new_df], how="vertical_relaxed")
        df = cls._cols_last(df)
        df.write_parquet(cls._parquet_path(table))
        return df

    @classmethod
    def delete_records(cls, table: str, res_ids: list[int]) -> pl.DataFrame | None:
        """Drop deleted-record rows (from auditlog unlink logs) and rewrite the parquet."""
        if not res_ids:
            return None
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
