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
from services.env_reader_service import EnvReaderService
from werkzeug.utils import redirect

import connectorx as cx
import marimo as mo
import odoorpc
import logging
import json

logger = logging.getLogger(__name__)
app = FastAPI()
router = APIRouter()
df_store = DFStorageService()
env_read = EnvReaderService()

PORT = env_read.get("ODOO_SERVER_PORT")
HOST = env_read.get("ODOO_SERVER_HOST")
POSTGRES_URL = env_read.get("POSTGRES_URL")

odoo = odoorpc.ODOO(HOST, port=PORT)

print(odoo.db.list())

odoo.login("odoo18", "admin", "admin")

user = odoo.env.user
env = odoo.env


def quote(strings):
    return [f'"{s}"' for s in strings]


def sanitize(fields: list[str]):
    return ", ".join(set(quote(fields)))


app = FastAPI()
router = APIRouter()


@router.get("/")
def handle_table_info():
    kpiten_config = env["kpiten.config"]
    kpiten_profiles = json.loads(kpiten_config.read_kpiten_config())

    for profile in kpiten_profiles:
        name = profile["name"]
        pr_id = profile["profile_id"]
        print(f"profile : {name}\nprofile_id : {pr_id}")

        print("\tTables: \n")
        for table in profile["tables"]:
            table_name = table["table"]
            tech_name = table["technical_name"]
            record_name = table["record_name"]
            fields = sanitize(table["fields"])
            all_fields = sanitize(table["all_fields"])

            print(f"SELECT {fields} FROM {tech_name} LIMIT 12")
            df = cx.read_sql(
                POSTGRES_URL,
                f"SELECT {fields} FROM {tech_name} LIMIT 12",
                return_type="polars",
            )

            df_store.store_df(pr_id, table_name, record_name, fields, df)

            print(
                f"\t\tTable : {table_name}\n\t\t\trecord_name : {record_name}\n\t\t\tfields={fields}\n\t\t\tall_fields={all_fields}\n\t\t\tprofile_id={pr_id}"
            )

    return redirect(code=301, location="/notebook")


marimo_server = mo.create_asgi_app().with_app(path="/notebook", root="./notebook.py")

app.include_router(router)
app.mount("/", marimo_server.build())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
