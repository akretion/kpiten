"""Data reads & store maintenance requests (per session data snapshot).

The dashboard asks kpiten-core to load / refresh a database through the sync
service ; reading back the per-user dataframes and the sync status is done
here, on top of the shared kpiten-core store.
"""

import logging

import polars as pl

from kpiten_core.backend import Backend
from kpiten_core import loaders
from kpiten_core.service import service as kpiten_service
from kpiten_core.store import DFStorage

logger = logging.getLogger(__name__)


def request_load(db: str, panel_id=None, wait=True, progress=None):
    """Ask kpiten-core to load a database (panel first, recent->oldest)."""
    kpiten_service.request_load(db, panel_id, wait, progress)


def request_refresh(db: str, wait=True, progress=None):
    """Ask kpiten-core to delta-refresh a database (Refresh data button)."""
    kpiten_service.request_refresh(db, wait, progress)


def pending_tables() -> set[str]:
    """Models still being progressively loaded (partial parquet)."""
    return loaders.pending_tables()


def progress(db: str) -> dict:
    """Progress of the progressive load of a db (current %, queued tables)."""
    return kpiten_service.get_progress(db)


def last_sync(backend: Backend, user_id: int) -> str | None:
    """Data age, in the user timezone, minutes precision."""
    return loaders.last_sync(backend, user_id)


def user_store(backend: Backend, user_id: int) -> dict[str, pl.DataFrame]:
    """Per-user view of the store.

    - columns are filtered by the user ACL (`kpiten.get_allowed_fields`)
    - translatable struct columns are destructured by the user lang
    """
    lang = backend.get_user_lang(user_id)
    store: dict[str, pl.DataFrame] = {}
    for table in DFStorage.list_table_names():
        try:
            allowed = backend.get_allowed_fields(table, user_id)
            row = DFStorage.retrieve_df(table, allowed_fields=allowed, lang=lang)
            if row:
                store[table] = row["df"]
        except Exception:
            logger.exception("user store fetch failed for %s", table)
    return store
