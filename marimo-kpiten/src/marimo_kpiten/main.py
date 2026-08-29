import json
from typing import Any

from fastapi import FastAPI, APIRouter, Response
from fastapi.responses import RedirectResponse
from marimo_kpiten.services.df_storage import DFStorage
from marimo_kpiten.services.dataframe_util import Df
from marimo_kpiten.services.file_state import FileState
from marimo_kpiten.services.RPC import RPC
from marimo_kpiten.services.env_reader import EnvReader
from marimo_kpiten.services.session_handler import SESSION_STATE, SessionHandler
from datetime import datetime

import polars as pl
import marimo as mo
import logging

logger = logging.getLogger(__name__)
app = FastAPI()
router = APIRouter()
df_store = DFStorage()
env = None

try:
    env = RPC().env
except Exception as e:
    logger.warning(f"Odoo connection failed:\n{e}")

if env is None:
    raise Exception("Odoo environment could not be initialized properly.")


@router.post("/")
def auth(uuid_dict: dict[Any, Any]):
    print(f"payload : {uuid_dict}")
    if uuid_dict.get("user_uuid") and env:
        log_ids = env["res.users.log"].search([("uuid", "=", uuid_dict["user_uuid"])])
        logs = env["res.users.log"].browse(log_ids)
        print(f"LOGS : {logs}")
        print(f"LOG_IDS : {log_ids}")
        if len(log_ids) > 0:
            FileState.store_state(
                data={
                    "user_id": str(logs[0].create_uid.id)
                },  # the first occurence is enough
            )

            df_build_success = build_global_dfs()
            if not df_build_success:
                return Response(
                    status_code=500,
                    content=json.dumps(
                        {
                            "error": "The server is unavailable. "
                            + "Please try again later, or contact support !"
                        }
                    ),
                )
            session_token = SessionHandler.new_session(uuid_dict["user_uuid"])
            return Response(
                status_code=200, content=json.dumps({"session": session_token})
            )
        else:
            return Response(
                status_code=403,
                content=json.dumps({"error": "No user matches this uuid"}),
            )
    else:
        return Response(
            status_code=403,
            content=json.dumps(
                {
                    "error": f"No uuid was provided. there needs to be a 'user_uuid'"
                    + "property in the sent JSON"
                }
            ),
        )


def build_global_dfs():
    if env:
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
            decimal = EnvReader.get("DECIMAL_TRUNCATE") or 0
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

        return True
    else:
        return False


@router.get("/build/auth")
def check(session: str):
    print(SessionHandler.sessions)
    if SessionHandler.check_session(session) == SESSION_STATE.VALID:
        return RedirectResponse(status_code=303, url="/build/")
    elif SESSION_STATE.EXISTS:
        return Response(
            status_code=403,
            content="<h1>Auth failed</h1><p></p>Your session is expired.",
        )
    else:
        return Response(
            status_code=403,
            content="<h1>Auth failed</h1><p></p>No session registered for this token.",
        )


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
