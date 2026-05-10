"""
TODO
- Find out how the dataflow from a connected odoo user to here will be.
> Right now, everything is hardcoded / read from the env, which disallows multi-user setups

- Determine how df_notebook.py will be aware of what tables it has to show. For now, the tables are hardcoded,
which disallows using different tables w/out changing the code.

- turn odoorpc into a singleton to avoid multiple connections in the same script.

"""

from fastapi import FastAPI, APIRouter
from services.df_file_storage_service import DFStorageService
from services.env_reader import EnvReader
from services.dataframe_util import Df
from werkzeug.utils import redirect
from pg_autojoin import SqlJoin

import connectorx as cx
import marimo as mo
import odoorpc
import logging
import json

logger = logging.getLogger(__name__)
app = FastAPI()
router = APIRouter()
df_store = DFStorageService()
env_ = EnvReader()

postgres_url = (
    f'postgresql://{env_.get("DB_USER")}:{env_.get("DB_PWD")}@'
    + f'{env_.get("DB_HOST")}:{env_.get("DB_PORT")}'
)
db_url = f'{postgres_url}/{env_.get("ODOO_DB")}'
odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))

print(odoo.db.list())

odoo.login(env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD"))

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
        conn = SqlJoin(
            db=env_.get("ODOO_DB"),
            user=env_.get("DB_USER"),
            password=env_.get("DB_PWD"),
            host=env_.get("DB_HOST"),
            port=env_.get("DB_PORT"),
        )
        conn.set_columns_to_retrieve(["name", "ref", "code"])
        conn.get_joins(table=table)
        sql, _ = conn.get_joined_query(table=table)
        return sql

    kpiten_profiles = json.loads(env["kpiten.config"].read_config())
    for profile in kpiten_profiles:
        name = profile["name"]
        pr_id = profile["profile_id"]
        print(f"profile : {name}\nprofile_id : {pr_id}")
        print("\tTables: \n")
        for tbl in profile["tables"]:
            fields = sanitize(tbl["fields"])
            all_fields = sanitize(tbl["all_fields"])
            sql = (
                f"SELECT {fields} FROM {tbl['table']} ORDER BY write_date ASC LIMIT 12",
            )
            print(sql)
            # sql = relationship_query("sale_order")
            df = cx.read_sql(db_url, sql[0], return_type="polars")
            transfo = Df(df)
            df = transfo.get_df()
            df_store.store_df(pr_id, tbl["table"], tbl["record_name"], fields, df)
            print(
                f"\t\tTable : {tbl['table']}\n\t\t\trecord_name : {tbl['record_name']}\n\t\t\tfields={fields}\n\t\t\tall_fields={all_fields}\n\t\t\tprofile_id={pr_id}"
            )

    return redirect(code=301, location="/notebook")


marimo_server = mo.create_asgi_app().with_app(path="/build", root="./build.py")

app.include_router(router)
app.mount("/", marimo_server.build())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
