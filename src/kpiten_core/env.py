import os
import threading
from contextlib import contextmanager

import dotenv

dotenv.load_dotenv()


def get(env_var, default=None):
    return os.environ.get(env_var, default)


data_path = get("DATA_PATH", "data_dir")
decimal_truncate = int(get("DECIMAL_TRUNCATE", "5"))

# Odoo RPC timeout in seconds (odoorpc default is 120s ; raise it so a slow
# chunked extract doesn't hard-fail mid-sync)
odoo_timeout = int(get("ODOO_TIMEOUT", "300"))

# Number of records fetched per RPC call during the paginated parquet sync
sync_page_size = int(get("SYNC_PAGE_SIZE", "5000"))

# Records pulled per background completion pass (recent->oldest initial load)
sync_batch_size = int(get("SYNC_BATCH_SIZE", "50000"))

# Seconds between two background completion passes in the dashboard apps
sync_interval = int(get("SYNC_INTERVAL", "60"))

# Direct-Postgres extraction mode (see loaders / the Odoo `kt` module) :
#   - "jsonrpc" : legacy ORM path (odoorpc), default
#   - "sql"     : Polars streams the Odoo-generated SELECT through connectorx
#   - "view"    : same but reads a persistent SQL view created by Odoo
extract_mode = get("EXTRACT_MODE", "jsonrpc")

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
