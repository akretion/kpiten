"""Data extraction & store maintenance (per session data snapshot)."""

import logging

import polars as pl

from kpiten_core.backend import Backend
from kpiten_core import loaders
from kpiten_core.store import DFStorage

logger = logging.getLogger(__name__)


def sync_store(backend: Backend, extraction_uid: int) -> dict[str, pl.DataFrame]:
    """Incremental parquet refresh (delta since last_sync + deletions).

    First call does a full extract, subsequent ones only pull the records
    created/updated since the last sync (see kpiten_core.loaders.sync_store).
    """
    return loaders.sync_store(backend, extraction_uid)


def build_store(backend: Backend, extraction_uid: int) -> dict[str, pl.DataFrame]:
    """Full extract of all datasets declared in Odoo (kpiten.dataset)."""
    return loaders.build_store(backend, extraction_uid)


def last_sync(backend: Backend, user_id: int) -> str | None:
    """Data age, in the user timezone, minutes precision."""
    return loaders.last_sync(backend, user_id)


def load_store(zip_path: str | None = None) -> dict[str, pl.DataFrame]:
    """Load dataframes from the existing parquet files."""
    return {
        table: DFStorage.retrieve_df(table)["df"]
        for table in DFStorage.list_table_names()
    }


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
