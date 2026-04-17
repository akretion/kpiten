import polars as pl
import json
import os
from polars import DataFrame
from services.env_reader_service import EnvReaderService

env_service = EnvReaderService()
data_path = env_service.get("TABLE_PATH") or "./"


class DFFileStorage:
    # TO DO : make a type for json metadata for better validation

    metadata_file_name = "metadata"
    parquet_file_name = "parquet"

    @staticmethod
    def store_df(table: str, record_name: str, df: DataFrame):
        os.mkdir(f"{data_path}/{table}")
        with open(
            f"{data_path}/{table}/{DFFileStorage.metadata_file_name}.json", "a"
        ) as meta:
            meta.write(
                json.dumps({"table": table, "record_name": record_name})
            )
        df.write_parquet(f"{data_path}/{table}/{DFFileStorage.parquet_file_name}")

    @staticmethod
    def retrieve_df(table: str) -> tuple[str, str, DataFrame]:
        """
        Returns: tuple(table, record_name, DataFrame)
        """

        metadata = open(
            f"{data_path}/{table}/{DFFileStorage.metadata_file_name}.json"
        )
        metadata_json = json.loads(metadata.read())

        record_name = metadata_json["record_name"]
        df = pl.read_parquet(
            f"{data_path}/{table}/{DFFileStorage.parquet_file_name}"
        )

        return (table, record_name, df)
