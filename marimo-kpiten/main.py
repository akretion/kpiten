from services.env_reader_service import EnvReaderService
from services.df_file_storage_service import DFFileStorage
from model.table_metada import TableMetadata
from model.graph_json import GraphJSON

from fastapi import FastAPI, APIRouter, Response
from polars import DataFrame

import marimo as mo
import connectorx as cx

import logging

logger = logging.getLogger(__name__)


app = FastAPI()
router = APIRouter()
env_service = EnvReaderService()

DATAFRAMES: list[DataFrame] = []


@router.post("/")
def handle_table_info(metadata: TableMetadata):
    print("Marimo Endpoint...")
    URI = env_service.get("POSTGRES_URL")
    # for testing only
    sanitized_fields = ", ".join(set(metadata.fields))
    if URI:
        df = cx.read_sql(
            URI,
            f"SELECT {sanitized_fields} FROM {metadata.table} LIMIT 10",
            return_type="polars",
        )
        print(df)
        DFFileStorage.store_df(
            metadata.table,
            metadata.record_name,
            df,  # type: ignore
        )
        return Response(status_code=200)
    else:
        logger.warning(f"No POSTGRES_URL variable defined in env")
        return Response(status_code=500)


@router.post("/graph_build")
def build_graph(graph_json: GraphJSON):
    print(graph_json)

marimo_server = mo.create_asgi_app().with_app(path="/notebook", root="./df_notebook.py")

app.include_router(router)
app.mount("/", marimo_server.build())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
