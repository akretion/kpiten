from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import RedirectResponse
from marimo_kpiten.services.df_storage import DFStorage
from marimo_kpiten.services.env_reader import EnvReader
from marimo_kpiten.services.dataframe_util import Df
from marimo_kpiten.services.file_state import FileState
from urllib.error import URLError
from odoorpc.error import RPCError
from datetime import datetime

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
env = None

try:
    odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))
except URLError as e:
    logger.warning(f"Odoo is not available:\n{e}")
except Exception as e:
    logger.warning(e)

try:
    odoo.login(env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD"))
    env = odoo.env
except RPCError as e:
    logger.warning(f"Odoo authentification failed: {e}")
except Exception as e:
    logger.warning(e)

if odoo is None:
    raise Exception("Odoo connection could not be initialized properly.")

if env is None:
    raise Exception("Odoo environment could not be initialized properly.")

app = FastAPI()
router = APIRouter()


@router.get("/")
def root():
    return {"message": "server is running. visit /login w/ an id to use the website"}


# TODO : NAVIGATE TO IT USING ODOO THEN CHANGE THIS TO POST
@router.get("/login")  # ?id = id
def login(id: int):
    FileState.store_state(state_type="state", data={"user_id": str(id)})
    return RedirectResponse("/df_process", status_code=303)


@router.get("/df_process")
def build_global_dfs():
    overall_start_time = datetime.now()
    config_ids = env["kpiten.config"].search([])
    loop_start_time = datetime.now()
    for conf in env["kpiten.config"].browse(config_ids):
        model = conf.model_id.model
        print(f"### Loop on {model} :  statistics ###")
        # print("Model is", model)
        # user id 2 have most of the grants
        record_time = datetime.now()
        records = env["kpiten"].get_record_vals(model, [], 2)
        record_time_end = datetime.now()
        print("record cpt : ", record_time_end - record_time)
        df = pl.DataFrame(records, strict=False, infer_schema_length=None)
        decimal = env_.get("DECIMAL_TRUNCATE") or 0
        fmetadata_time = datetime.now()
        fields_metadata = env["kpiten"].get_fields_metadata(model)
        fmetadata_time_end = datetime.now()
        print("fmetadata : ", fmetadata_time_end - fmetadata_time)
        transfo = Df(df, fields_metadata, decimal_truncate=int(decimal))
        df = transfo.get_df()
        df_store.store_df(model, df)
    loop_end_time = datetime.now()
    overall_end_time = datetime.now()

    print("#### Overall Statistics ####\n")
    print(f"overall time : {overall_end_time - overall_start_time}")
    print(f"loop : {loop_end_time - loop_start_time}")
    print("#### --- ####")
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
