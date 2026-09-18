"""Parquet sync service (kpiten-core).

The dashboard fronts (shiny / nicegui) ask for a sync on demand (the
"Refresh data" button) ; extraction runs straight from Postgres via
connectorx (see `loaders`), fast enough that no background/periodic
completion is needed.

`request_refresh(db)` is serialized by a per-db lock so two concurrent
requests (e.g. two users clicking "Refresh" on the same db) never write the
same parquet at the same time.
"""

import logging
import threading

from kpiten_core import env, loaders
from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self):
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._backends: dict[str, object] = {}

    def request_refresh(self, db: str, progress=None):
        """Incremental delta sync of a db (Refresh data button), synchronous."""
        self._execute(db, self._db_lock(db), progress)

    def _db_lock(self, db: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(db, threading.Lock())

    def _backend(self, db: str):
        backend = self._backends.get(db)
        if backend is None:
            backend = Backend.create(db=db)
            self._backends[db] = backend
        return backend

    def _execute(self, db: str, lock: threading.Lock, progress):
        with lock:
            try:
                with env.db_scope(db):
                    backend = self._backend(db)
                    loaders.sync_store(backend, backend.env.user.id, progress)
            except Exception:
                logger.exception("sync failed for db %s", db)


# module-level singleton, shared by the apps
service = SyncService()
