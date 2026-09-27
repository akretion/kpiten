"""Data reads & store maintenance requests (per session data snapshot).

The dashboard asks kpiten-core to refresh a database through the sync
service ; reading back the per-user dataframes and the sync status is done
here, on top of the shared kpiten-core store.
"""

import datetime

import polars as pl

from kpiten_core.backend import Backend
from kpiten_core import loaders
from kpiten_core.service import service as kpiten_service


def request_refresh(db: str, progress=None):
    """Ask kpiten-core to sync a database now (an empty store on the first load)."""
    kpiten_service.request_refresh(db, progress)


def scheduled_refresh(db: str, slot: float) -> bool:
    """The sync asked by the Refresh data button : at `slot`, the next boundary of 5
    minutes (`kpiten_core.service.next_slot`), one for all the requests of the slot.
    Blocks until it is over."""
    return kpiten_service.scheduled_refresh(db, slot)


def last_sync(backend: Backend, user_id: int) -> str | None:
    """Data age, in the user timezone, minutes precision."""
    return loaders.last_sync(backend, user_id)


def user_time(backend: Backend, user_id: int, epoch: float) -> str:
    """A time (epoch seconds) as the user reads it : their timezone, their format."""
    moment = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    return loaders.user_datetime(backend, user_id, moment, date=False)


def is_stale(backend: Backend) -> bool:
    """The last sync is older than `DATA_STALE_HOURS` (the date shown in orange)."""
    from kpiten_core import env

    with env.db_scope(backend.db):
        return loaders.is_stale()


def user_store(backend: Backend, user_id: int) -> dict[str, pl.LazyFrame]:
    """Per-user view of the store (see `kpiten_core.loaders.user_store`) :

    - columns are filtered by the user ACL (`kpiten.get_allowed_fields`)
    - rows are filtered by the user record rules (`kpiten.get_access_query`)
    - translatable struct columns are destructured by the user lang
    - the shared derived tables are there too, by their name (`loaders.tile_store`)
    """
    return loaders.tile_store(backend, user_id)
