"""
TODO
- Find out how the dataflow from a connected odoo user to here will be.
> Right now, everything is hardcoded / read from the env, which disallows multi-user setups

- Determine how df_notebook.py will be aware of what tables it has to show. For now, the tables are hardcoded,
which disallows using different tables w/out changing the code.

- turn odoorpc into a singleton to avoid multiple connections in the same script.

"""

from fastapi import FastAPI, APIRouter
from marimo_kpiten.services.df_storage import DFStorage
from marimo_kpiten.services.env_reader import EnvReader
from marimo_kpiten.services.dataframe_util import Df
from werkzeug.utils import redirect
from pg_autojoin import SqlJoin
from urllib.error import URLError
from odoorpc.error import RPCError

import connectorx as cx
import marimo as mo
import odoorpc
import logging
import json

logger = logging.getLogger(__name__)
app = FastAPI()
router = APIRouter()
df_store = DFStorage()
env_ = EnvReader()
odoo = None

postgres_url = (
    f'postgresql://{env_.get("DB_USER")}:{env_.get("DB_PWD")}@'
    + f'{env_.get("DB_HOST")}:{env_.get("DB_PORT")}'
)
DB_URL = f'{postgres_url}/{env_.get("ODOO_DB")}'
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


def quote(strings):
    return [f'"{s}"' for s in strings]


def sanitize(fields: list[str]):
    return ", ".join(quote(fields))


app = FastAPI()
router = APIRouter()


@router.get("/")
def handle_table_info():
    def relationship_query(table):
        logger.warning(f"relationship query({table})")
        conn = SqlJoin(
            db=env_.get("ODOO_DB"),
            user=env_.get("DB_USER"),
            password=env_.get("DB_PWD"),
            host=env_.get("DB_HOST"),
            port=env_.get("DB_PORT"),
        )
        conn.set_columns_to_retrieve(["name", "ref", "code"])
        # depends on the user
        conn.set_json_key_pref(env.context.get("lang") or "en_US")
        conn.set_fallback_json_key("en_US")
        sql = conn.get_joined_query(table=table)
        return sql

    kpiten_profiles = json.loads(env["kpiten.config"].read_config())
    print("------ PARSING KPITEN PROFILES ------")
    print("--- Looping on models ---")
    for profile in kpiten_profiles:
        name = profile["name"]
        pr_id = profile["profile_id"]
        main_record_name = profile["main_record_name"]
        main_model = profile["main_model"]
        main_model_fields = profile["main_model_fields"]

        sql = relationship_query(main_model)
        main_df = cx.read_sql(DB_URL, sql, return_type="polars")
        transfo = Df(main_df)
        main_df = transfo.get_df()

        df_store.store_df(
            pr_id, main_model, main_record_name, main_model_fields, main_df
        )

        print(f"profile : {name}\nprofile_id : {pr_id}")
        print(f"Main model : {main_model}\n")
        print(f"Main model fields : {main_model_fields}")

        for tbl in profile["models"]:
            fields = sanitize(tbl["fields"])
            all_fields = sanitize(tbl["all_fields"])
            sql = (
                f"SELECT {fields} FROM {tbl['table']} ORDER BY write_date ASC LIMIT 100",
            )
            logger.warning(f"generated sql : {sql}")
            sql = relationship_query(tbl["table"])
            df = cx.read_sql(DB_URL, sql, return_type="polars")
            transfo = Df(df)
            df = transfo.get_df()
            df_store.store_df(pr_id, tbl["table"], tbl["record_name"], fields, df)
            print(
                f"\t\tTable : {tbl['table']}\n\t\t\trecord_name : {tbl['record_name']}\n\t\t\tfields={fields}\n\t\t\tall_fields={all_fields}\n\t\t\tprofile_id={pr_id}"
            )

    print("--- end of loop ---")
    print("------ KPITEN PROFILES PARSING END ------")
    return redirect(code=301, location="/build")


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
