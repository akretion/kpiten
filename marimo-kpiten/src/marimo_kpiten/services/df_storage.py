import polars as pl
import logging
import pathlib
from pathlib import Path
from polars import DataFrame
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


data_path = "../generated"

logger = logging.getLogger(__name__)


class DFStorage:
    # TODO : make a type for json metadata for better validation

    df_data_dir_name = "dataframes"
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
    def _is_forbidden_column(c: str, verbose=True):
        forbidden_columns = ["__last_update"]
        has_illegal_prefix = c.startswith("__")
        is_forbidden = c in forbidden_columns

        if (is_forbidden or has_illegal_prefix) and verbose:
            print(f"ignored forbidden column '{c}'")

        return not has_illegal_prefix or not is_forbidden

    @staticmethod
    def store_df(table: str, df: DataFrame):
        Path(f"{data_path}").mkdir(exist_ok=True)
        Path(f"{data_path}/{DFStorage.df_data_dir_name}/").mkdir(exist_ok=True)
        Path(f"{data_path}/{DFStorage.df_data_dir_name}/{table}/").mkdir(exist_ok=True)
        df.write_parquet(
            f"{data_path}/{DFStorage.df_data_dir_name}/{table}/{table}.{DFStorage.parquet_file_ext}"
        )

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
        allowed_fields = RPC().env["kpiten"].get_allowed_fields(table, curr_uid)
        print(f"ALLOWED FIELDS (before alteration) : {allowed_fields}")
        try:
            df = pl.read_parquet(
                f"{data_path}/{DFStorage.df_data_dir_name}/{table}/{table}.{DFStorage.parquet_file_ext}"
            )
            sanitized_allowed_fields = filter(
                DFStorage._is_forbidden_column, allowed_fields
            )
            sanitized_allowed_fields = DFStorage._filter_not_found_columns(
                df, table, sanitized_allowed_fields, True
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
    def retrieve_all_dfs() -> list[DF_META]:
        generated = pathlib.Path(f"{data_path}/{DFStorage.df_data_dir_name}")
        tables: list[DF_META] = []
        res = generated.iterdir()
        for file in res:
            df = DFStorage.retrieve_df(file.name)
            if df:
                tables.append(df)
        return tables
