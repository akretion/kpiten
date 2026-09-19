import os
import pathlib
import threading
from contextlib import contextmanager

import dotenv


def find_dotenv(start: pathlib.Path | None = None) -> str:
    """The `.env` of the project, whatever the way the process was started.

    python-dotenv looks from the file that imports it, or from the working
    directory (`python -m`, `python -c`, interactive) : the same code then
    reads different files, or none, depending on where a cron job or a shell
    happens to be. Here it is the first `.env` above the package sources
    (src/kpiten-core/.env), else the one of the working directory.
    """
    for parent in (start or pathlib.Path(__file__)).resolve().parents:
        if (parent / ".env").is_file():
            return str(parent / ".env")
    return dotenv.find_dotenv(usecwd=True)


dotenv.load_dotenv(find_dotenv())


def get(env_var, default=None):
    return os.environ.get(env_var, default)


data_path = get("DATA_PATH", "data_dir")
decimal_truncate = int(get("DECIMAL_TRUNCATE", "5"))

# Odoo RPC timeout in seconds (odoorpc default is 120s ; raise it so a slow
# chunked extract doesn't hard-fail mid-sync)
odoo_timeout = int(get("ODOO_TIMEOUT", "300"))

# Dev / tests only : a dashboard opened without an SSO session runs as the RPC
# login user (ODOO_LOGIN, usually admin), i.e. with no per-user restriction.
# Off by default : without a session the dashboard asks to log in from Odoo.
allow_rpc_user = get("ALLOW_RPC_USER", "0") == "1"

# Number of rows fetched per connectorx page during the parquet sync. Each page
# is one query : ~30 ms of fixed cost (connection, planning of the joined
# select) + ~9 us per row, so small pages are dominated by the fixed cost
# (5 000 rows : 67k rows/s, 100 000 : 161k rows/s). A page is about one block
# of PARTITION_SIZE ids, which the sync holds in memory anyway.
sync_page_size = int(get("SYNC_PAGE_SIZE", "100000"))

# Guardrails on what a tile hands to the front : a table of 800k rows or a bar
# chart with 100k bars freezes the browser tab, whatever the server does.
# Rows kept by a table tile (pivot / union / data), the rest is cut off
tile_max_rows = int(get("TILE_MAX_ROWS", "500"))
# Bars kept by a graph on a categorical axis (the rest is dropped, or folded in
# an "Others" bar with `others = true`)
# Explore : the rows of a panel taken out of the dashboard (see `explore`)
explore_max_rows = int(get("EXPLORE_MAX_ROWS", "500000"))  # per table
explore_dir = get("EXPLORE_DIR")  # default : `explore` next to DATA_PATH
explore_ttl_hours = int(get("EXPLORE_TTL_HOURS", "1"))  # a leftover export is purged

tile_max_categories = int(get("TILE_MAX_CATEGORIES", "50"))
# Points kept by a graph on a date axis (above : grouped by month, then cut)
tile_max_points = int(get("TILE_MAX_POINTS", "1000"))
# Distinct values of the pivot `column` (one html column each)
tile_max_pivot_columns = int(get("TILE_MAX_PIVOT_COLUMNS", "100"))
# Values offered by a panel dimension filter (most frequent first)
dimension_max_values = int(get("DIMENSION_MAX_VALUES", "1000"))

# Records per stored block : the parquet of a table is split by id ranges of
# this size (id // PARTITION_SIZE), so a full extraction never holds more than
# one block and a delta only rewrites the blocks it touches.
partition_size = int(get("PARTITION_SIZE", "100000"))

# Direct-Postgres extraction mode (see loaders / the Odoo `kt` module) :
#   - "sql"  : Polars streams the Odoo-generated SELECT through connectorx (default)
#   - "view" : same but reads a persistent SQL view created by Odoo
extract_mode = get("EXTRACT_MODE", "sql")

# Postgres connection used by the direct extraction modes ("sql" / "view").
# Defaults mirror a typical local Odoo instance (db user / password from the
# Odoo server config, e.g. rc / rc2). The database is the scoped one.
pg_host = get("PG_HOST", "localhost")
pg_port = int(get("PG_PORT", "5432"))
pg_user = get("PG_USER", "odoo")
pg_pwd = get("PG_PWD", "odoo")
# Database for the direct extraction ; empty (default) = the scoped database.
pg_db = get("PG_DB", "")

# Odoo database the parquet scoping targets (set by the UI apps on db switch).
# Reads prefer the thread-local value (set by the sync service / db_scope) so
# background syncs on several databases don't clash with each other or with
# the request threads.
current_db = None
_local = threading.local()


def active_db() -> str | None:
    """Database the current thread is scoped to (thread-local, else global)."""
    return getattr(_local, "db", None) or current_db


@contextmanager
def db_scope(db: str | None):
    """Temporarily scope the parquet storage to a specific database.

    Used by the sync service so each database's sync writes to its own
    parquet dir regardless of the shared `env.current_db`.
    """
    previous = getattr(_local, "db", None)
    _local.db = db
    try:
        yield
    finally:
        _local.db = previous
