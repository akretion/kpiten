import polars as pl
import logging
import pathlib
from pathlib import Path
from polars import DataFrame
from marimo_kpiten.common import DATA_PATH
from marimo_kpiten.services.env_reader import EnvReader
from marimo_kpiten.services.RPC import RPC
from marimo_kpiten.services.file_state import FileState
from marimo_kpiten.services.dataframe_util import Df
from typing import TypedDict

"""
TODO
- change the return type of retrieve df to a pydantic type so it's easier to read and use
- (minor) make it so that profile_id isn't stored into each table to limit duplication
"""

env_ = EnvReader()


class DF_META(TypedDict):
    table: str
    df: DataFrame


logger = logging.getLogger(__name__)


class DFStorage:
    # TODO : make a type for json metadata for better validation

    df_data_dir_name = "parquet"
    metadata_file_name = "metadata"
    parquet_file_ext = "parquet"

    @staticmethod
    def _filter_not_found_columns(
        df: DataFrame, name: str, columns: list[str], verbose=False
    ):
        found = []
        not_found = []
        for c in columns:
            try:
                res = df.select(c)
                found.append(c)
            except pl.exceptions.ColumnNotFoundError as CNF:
                not_found.append(c)
        if verbose:
            if len(not_found) > 0:
                logger.warning(f"[{name}] Those columns were not found : {not_found}")
            else:
                logger.warning(f"[{name}] Every column was found.")
        return found

    @staticmethod
    def _is_forbidden_column(c: str, verbose=False):
        forbidden_columns = ["__last_update"]
        has_illegal_prefix = c.startswith("__")
        is_forbidden = c in forbidden_columns

        if (is_forbidden or has_illegal_prefix) and verbose:
            print(f"ignored forbidden column '{c}'")

        return not has_illegal_prefix or not is_forbidden

    @staticmethod
    def _is_external_column(c: str, verbose=False):
        if "." in c or c[-1] == "_":
            if verbose:
                print(f"column {c} is recognized as external.")
            return True
        return False

    @staticmethod
    def store_df(table: str, df: DataFrame):
        Path(f"{DATA_PATH}").mkdir(exist_ok=True)
        Path(f"{DATA_PATH}/{DFStorage.df_data_dir_name}/").mkdir(exist_ok=True)
        df.write_parquet(
            f"{DATA_PATH}/{DFStorage.df_data_dir_name}/{table}.{DFStorage.parquet_file_ext}"
        )

    @staticmethod
    def _allowed_fields_pipeline(df, table: str, curr_uid: int):
        # Get allowed fields from odoo side
        allowed_fields = RPC().env["kpiten"].get_allowed_fields(table, curr_uid)
        # isolate external columns
        dotted_columns = filter(DFStorage._is_external_column, df.columns)
        # merge the two lists
        allowed_fields = list(set([*allowed_fields, *dotted_columns]))
        # remove forbidden columns
        sanitized_allowed_fields = filter(
            DFStorage._is_forbidden_column, allowed_fields
        )
        # remove columns that are not in the actual dataframe, even
        # if they are allowed columns
        sanitized_allowed_fields = DFStorage._filter_not_found_columns(
            df, table, sanitized_allowed_fields, False
        )
        return sanitized_allowed_fields

    @staticmethod
    def retrieve_df(table: str) -> DF_META | None:
        """
        NAME: retrieve_df
        RAISES: Exception (when the asked dataframe doesn't exist)
        RETURNS: tuple(profile_id, table_name, record_name, fields, DataFrame)
        """
        if table == "notebook_state":
            return None

        curr_uid = int(FileState.retrieve_state("user_id"))
        try:
            df = pl.read_parquet(
                f"{DATA_PATH}/{DFStorage.df_data_dir_name}/{table}.{DFStorage.parquet_file_ext}"
            )
            sanitized_allowed_fields = DFStorage._allowed_fields_pipeline(
                df, table, curr_uid
            )
            df = df.select(sanitized_allowed_fields)
            struct_cols = [
                col
                for col, dtype in zip(df.columns, df.dtypes)
                if isinstance(dtype, pl.Struct)
            ]
            locale = RPC().env["res.users"].browse(curr_uid).lang
            df = df.with_columns(
                [pl.col(col).struct.field(locale).alias(col) for col in struct_cols]
            )

            return {
                "table": table,
                "df": df,
            }
        except FileNotFoundError as FNFE:
            raise Exception(
                f"No such table was stored : {table}. Complete Exception : \n{FNFE}"
            )

    @staticmethod
    def list_table_names() -> list[str]:
        df_dir = pathlib.Path(f"{DATA_PATH}/{DFStorage.df_data_dir_name}")
        if not df_dir.exists():
            return []
        return [
            file.stem
            for file in df_dir.iterdir()
            if file.is_file() and file.suffix == f".{DFStorage.parquet_file_ext}"
        ]

    @staticmethod
    def retrieve_all_dfs() -> list[DF_META]:
        tables: list[DF_META] = []
        for name in DFStorage.list_table_names():
            df = DFStorage.retrieve_df(name)
            if df:
                tables.append(df)
        return tables
