import polars as pl
import json
import logging
import pathlib
from pathlib import Path
from polars import DataFrame
from marimo_kpiten.services.env_reader import EnvReader
from typing import TypedDict

"""
TODO
- change the return type of retrieve df to a pydantic type so it's easier to read and use
- (minor) make it so that profile_id isn't stored into each table to limit duplication
"""

env_ = EnvReader()


class DF_META(TypedDict):
    profile_id: int
    table: str
    record_name: str
    fields: list[str]
    df: DataFrame


data_path = env_.get("DATA_PATH") or "../generated"

logger = logging.getLogger(__name__)


class DFStorageService:
    # TODO : make a type for json metadata for better validation

    df_data_dir_name = "dataframes"
    metadata_file_name = "metadata"
    parquet_file_ext = "parquet"

    @staticmethod
    def store_df(
        profile_id: int, table: str, record_name: str, fields: list[str], df: DataFrame
    ):
        Path(f"{data_path}").mkdir(exist_ok=True)
        Path(f"{data_path}/{DFStorageService.df_data_dir_name}/").mkdir(exist_ok=True)
        Path(f"{data_path}/{DFStorageService.df_data_dir_name}/{table}/").mkdir(
            exist_ok=True
        )
        with open(
            f"{data_path}/{DFStorageService.df_data_dir_name}/{table}/{DFStorageService.metadata_file_name}.json",
            "w+",
        ) as meta:
            meta.write(
                json.dumps(
                    {
                        "profile_id": profile_id,
                        "table": table,
                        "record_name": record_name,
                        "fields": fields,
                    }
                )
            )
        df.write_parquet(
            f"{data_path}/{DFStorageService.df_data_dir_name}/{table}/{table}.{DFStorageService.parquet_file_ext}"
        )

    @staticmethod
    def retrieve_df(table: str) -> DF_META | None:
        """
        NAME: retrieve_df
        RAISES: Exception (when the asked dataframe doesn't exist)
        RETURNS: tuple(profile_id, table_name, record_name, fields, DataFrame)
        """
        if table == "notebook_state":
            print("that's the notebooks state, early return")
            return None

        try:
            with open(
                f"{data_path}/{DFStorageService.df_data_dir_name}/{table}/{DFStorageService.metadata_file_name}.json"
            ) as mtdt:
                metadata_json = json.loads(mtdt.read())

                profile_id = metadata_json["profile_id"]
                record_name = metadata_json["record_name"]
                fields = metadata_json["fields"]
                df = pl.read_parquet(
                    f"{data_path}/{DFStorageService.df_data_dir_name}/{table}/{table}.{DFStorageService.parquet_file_ext}"
                )

                return {
                    "profile_id": profile_id,
                    "table": table,
                    "record_name": record_name,
                    "fields": fields,
                    "df": df,
                }

        except FileNotFoundError as FNFE:
            raise Exception(
                f"No such table was stored : {table}. Complete Exception : \n{FNFE}"
            )

    @staticmethod
    def retrieve_all_dfs() -> list[DF_META]:
        generated = pathlib.Path(f"{data_path}/{DFStorageService.df_data_dir_name}")
        tables: list[DF_META] = []

        res = generated.iterdir()
        for file in res:
            df = DFStorageService.retrieve_df(file.name)
            if df:
                tables.append(df)

        return tables
