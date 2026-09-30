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
    minutes (`kpiten_core.service.next_slot`), one for all the requests of the slot,
    or now when `kt.config` does not group the syncs. Blocks until it is over."""
    return kpiten_service.scheduled_refresh(db, slot)


def last_sync(backend: Backend, user_id: int) -> str | None:
    """Data age, in the user timezone, minutes precision."""
    return loaders.last_sync(backend, user_id)


def user_time(backend: Backend, user_id: int, epoch: float) -> str:
    """A time (epoch seconds) as the user reads it : their timezone, their format."""
    moment = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    return loaders.user_datetime(backend, user_id, moment, date=False)


def keep_backfilling(db: str):
    """A fresh database got its recent records : its history comes 3 months every 5
    minutes, in the background (`kpiten_core.service.keep_backfilling`)."""
    kpiten_service.keep_backfilling(db)


def history_since(backend: Backend, user_id: int) -> str | None:
    """While the history is loading : the date it reaches, as the user reads a date ;
    None when it is complete."""
    from kpiten_core import env

    with env.db_scope(backend.db):
        since = loaders.backfill_since()
    return (
        None
        if since is None
        else loaders.user_datetime(backend, user_id, since, time=False)
    )


def sync_stamp(db: str) -> str:
    """The time of the last sync of the store (raw) : a page sees a sync made
    without it (the history, another user) and draws its tiles again."""
    from kpiten_core import env
    from kpiten_core.store import DFStorage

    with env.db_scope(db):
        stamps = [DFStorage.last_sync(t) for t in DFStorage.list_table_names()]
    return max((s for s in stamps if s), default="")


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
