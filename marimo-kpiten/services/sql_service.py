from model.table_metadata import TableMetadata, KpitenProfile
from services.df_file_storage_service import DFStorageService
import connectorx as cx
from polars import DataFrame
import logging

df_storage_service = DFStorageService()
logger = logging.getLogger(__name__)

missing_uri_message = lambda: "URI was not set, please do so by editing .env"


class SQLService:
    URI: str | None = None

    def __new__(cls, *args, **kwagrs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def is_uri_set(self):
        return SQLService.URI is None

    def get_sanitized_fields(self, fields: list[str]):
        return ", ".join(set(fields))

    def store_df(self, metadata: TableMetadata, df: DataFrame):
        df_storage_service.store_df(metadata.table, metadata.record_name, df)

    def get_dataframe(
        self, table_metadata: TableMetadata, store: bool = True
    ) -> DataFrame:
        """
        get_dataframe
        ===
        :DESCRIPTION: returns dataframes of tables described by metadata passed in parameter.
        :RAISES: Exception if no URI was set.
        :PARAMS:
            - store (bool): stores read dataframes for later use (default=True)
        """
        sanitized_fields = self.get_sanitized_fields(table_metadata.fields)
        if self.is_uri_set() and len(sanitized_fields) is not 0:
            df = cx.read_sql(
                SQLService.URI,
                f"SELECT {sanitized_fields} FROM {table_metadata.table} LIMIT 10",
                return_type="polars",
            )
            if store:
                self.store_df(df)
            return df

        else:
            raise Exception(missing_uri_message())

    def get_all_dataframes(
        self, table_meta_list: KpitenProfile, store: bool = True
    ) -> list[DataFrame]:
        dataframes: list[DataFrame] = []
        for meta in table_meta_list.tables:
            try:
                df = self.get_dataframe(meta, store)
                dataframes.append(df)
                self.store_df(meta, df)
            except Exception as EX:
                logger.critical(missing_uri_message())

        return dataframes
