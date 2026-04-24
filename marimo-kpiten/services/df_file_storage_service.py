import polars as pl
import json
import logging
from pathlib import Path
from polars import DataFrame
from services.env_reader_service import EnvReaderService

env_service = EnvReaderService()
data_path = env_service.get("TABLE_PATH") or "./"

logger = logging.getLogger(__name__)


class DFFileStorage:
    # TO DO : make a type for json metadata for better validation

    metadata_file_name = "metadata"
    parquet_file_ext = "parquet"

    @staticmethod
    def store_df(table: str, record_name: str, df: DataFrame):
        Path(f"{data_path}").mkdir(exist_ok=True)
        Path(f"{data_path}/{table}").mkdir(exist_ok=True)
        with open(
            f"{data_path}/{table}/{DFFileStorage.metadata_file_name}.json", "w+"
        ) as meta:
            meta.write(json.dumps({"table": table, "record_name": record_name}))
        df.write_parquet(
            f"{data_path}/{table}/{table}.{DFFileStorage.parquet_file_ext}"
        )

    @staticmethod
    def retrieve_df(table: str) -> tuple[str, str, DataFrame]:
        """
        NAME: retrieve_df
        RAISES: Exception (when the asked dataframe doesn't exist)
        RETURNS: tuple(table, record_name, DataFrame)
        """
        try:
            with open(
                f"{data_path}/{table}/{DFFileStorage.metadata_file_name}.json"
            ) as mtdt:
                metadata_json = json.loads(mtdt.read())

                record_name = metadata_json["record_name"]
                df = pl.read_parquet(
                    f"{data_path}/{table}/{table}.{DFFileStorage.parquet_file_ext}"
                )

                return (table, record_name, df)

        except FileNotFoundError as FNFE:
            raise Exception(f"No such table was stored : {table}")
