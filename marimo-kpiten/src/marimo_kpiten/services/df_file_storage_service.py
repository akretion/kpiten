import polars as pl
import json
import logging
from pathlib import Path
from polars import DataFrame
from services.env_reader import EnvReader

"""
TODO
- change the return type of retrieve df to a pydantic type so it's easier to read and use
- (minor) make it so that profile_id isn't stored into each table to limit duplication
"""

data_path = './generated'

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
    def retrieve_df(table: str) -> tuple[int, str, str, list[str], DataFrame]:
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

                return (profile_id, table, record_name, fields, df)

        except FileNotFoundError as FNFE:
            raise Exception(f"No such table was stored : {table}")
