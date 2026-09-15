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
