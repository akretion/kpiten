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


class DF_META(TypedDict):
    profile_id: int
    table: str
    record_name: str
    fields: list[str]
    df: DataFrame


data_path = "../generated"

logger = logging.getLogger(__name__)


class DFStorageService:
    # TODO : make a type for json metadata for better validation

    metadata_file_name = "metadata"
    parquet_file_ext = "parquet"

    @staticmethod
    def store_df(
        profile_id: int, table: str, record_name: str, fields: list[str], df: DataFrame
    ):
        Path(f"{data_path}").mkdir(exist_ok=True)
        Path(f"{data_path}/{table}").mkdir(exist_ok=True)
        with open(
            f"{data_path}/{table}/{DFStorageService.metadata_file_name}.json", "w+"
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
            f"{data_path}/{table}/{table}.{DFStorageService.parquet_file_ext}"
        )

    @staticmethod
    def retrieve_df(table: str) -> DF_META:
        """
        NAME: retrieve_df
        RAISES: Exception (when the asked dataframe doesn't exist)
        RETURNS: tuple(profile_id, table_name, record_name, fields, DataFrame)
        """
        try:
            with open(
                f"{data_path}/{table}/{DFStorageService.metadata_file_name}.json"
            ) as mtdt:
                metadata_json = json.loads(mtdt.read())

                profile_id = metadata_json["profile_id"]
                record_name = metadata_json["record_name"]
                fields = metadata_json["fields"]
                df = pl.read_parquet(
                    f"{data_path}/{table}/{table}.{DFStorageService.parquet_file_ext}"
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
        generated = pathlib.Path(data_path)
        tables: list[DF_META] = []

        res = generated.iterdir()
        for file in res:
            tables.append(DFStorageService.retrieve_df(file.name))

        return tables
