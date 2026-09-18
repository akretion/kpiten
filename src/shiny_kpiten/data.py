"""Data reads & store maintenance requests (per session data snapshot).

The dashboard asks kpiten-core to refresh a database through the sync
service ; reading back the per-user dataframes and the sync status is done
here, on top of the shared kpiten-core store.
"""

import polars as pl

from kpiten_core.backend import Backend
from kpiten_core import loaders
from kpiten_core.service import service as kpiten_service


def request_refresh(db: str, progress=None):
    """Ask kpiten-core to sync a database (Refresh data button)."""
    kpiten_service.request_refresh(db, progress)


def last_sync(backend: Backend, user_id: int) -> str | None:
    """Data age, in the user timezone, minutes precision."""
    return loaders.last_sync(backend, user_id)


def user_store(backend: Backend, user_id: int) -> dict[str, pl.DataFrame]:
    """Per-user view of the store (see `kpiten_core.loaders.user_store`) :

    - columns are filtered by the user ACL (`kpiten.get_allowed_fields`)
    - rows are filtered by the user record rules (`kpiten.get_access_query`)
    - translatable struct columns are destructured by the user lang
    """
    return loaders.user_store(backend, user_id)
