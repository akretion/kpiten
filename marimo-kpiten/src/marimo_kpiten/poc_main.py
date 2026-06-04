from fastapi import FastAPI, APIRouter
from fastapi.responses import RedirectResponse
from marimo_kpiten.services.df_file_storage_service import DFStorage
from marimo_kpiten.services.env_reader import EnvReader
from marimo_kpiten.services.dataframe_util import Df
from marimo_kpiten.services.file_state import FileState
from werkzeug.utils import redirect
from urllib.error import URLError
from odoorpc.error import RPCError

import polars as pl
import marimo as mo
import odoorpc
import logging

logger = logging.getLogger(__name__)
app = FastAPI()
router = APIRouter()
df_store = DFStorage()
env_ = EnvReader()
odoo = None

try:
    odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))
except URLError as e:
    logger.warning(f"Odoo is not available:\n{e}")
except Exception as e:
    logger.warning(e)

try:
    odoo.login(env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD"))
except RPCError as e:
    logger.warning(f"Odoo authentification failed: {e}")
except Exception as e:
    logger.warning(e)

env = odoo.env

app = FastAPI()
router = APIRouter()


@router.get("/")
def root():
    return {"message": "server is running. visit /login w/ an id to use the website"}


# TODO : NAVIGATE TO IT USING ODOO THEN CHANGE THIS TO POST
@router.get("/login")
def login(id: int):
    FileState.store_state(state_type="state", data={"user_id": str(id)})
    return RedirectResponse("/df_process", status_code=303)


@router.get("/df_process")
def build_global_dfs():
    config_ids = env["kpiten.config"].search([])
    for conf in env["kpiten.config"].browse(config_ids):
        model = conf.model_id.model
        print("Model is", model)
        # user id 2 have most of the grants
        records = env["kpiten"].get_record_vals(model, [], 2, limit=100)
        df = pl.DataFrame(records, strict=False, infer_schema_length=None)
        decimal = env_.get("DECIMAL_TRUNCATE") or 0
        fields_metadata = env["kpiten"].get_fields_metadata(model)
        transfo = Df(df, fields_metadata, decimal_truncate=int(decimal))
        df = transfo.get_df()
        df_store.store_df(model, df)
    return RedirectResponse("/build", status_code=303)


marimo_server = (
    mo.create_asgi_app()
    .with_app(path="/build", root="./build.py")
    .with_app(path="/kpi", root="./kpi.py")
)

app.include_router(router)
app.mount("/", marimo_server.build())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
