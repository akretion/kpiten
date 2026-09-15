"""Autonomous parquet sync service (kpiten-core).

The dashboard fronts (shiny / nicegui) only *ask* for a sync ; this service
owns the background completion of the recent->oldest progressive load, with
one completion queue per Odoo database.

- `request_load(db, panel_id)` : seed / advance the progressive load of a db.
- `request_refresh(db)`       : incremental delta sync (Refresh data button).
- background thread           : keeps pulling one batch per interval for every
                                database that still has work, until complete.

Each operation is scoped to its database (thread-local, see `env.db_scope`)
and serialized by a per-db lock so a synchronous request and the background
tick never write the same parquet at the same time.
"""

import logging
import threading

from kpiten_core import env, loaders
from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, interval: int | None = None):
        self.interval = interval or env.sync_interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._active: set[str] = set()
        self._backends: dict[str, object] = {}

    # ---- lifecycle -----------------------------------------------------
    def start(self):
        """Start the background completion thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._tick, name="kpiten-sync", daemon=True
        )
        self._thread.start()
        logger.info("kpiten sync service started (interval=%ss)", self.interval)

    def stop(self):
        """Stop the background completion thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("kpiten sync service stopped")

    def active(self) -> bool:
        """Whether any database still has pending completion work."""
        with self._lock:
            return bool(self._active)

    # ---- API -----------------------------------------------------------
    def request_load(
        self, db: str, panel_id: int | None = None, wait: bool = True, progress=None
    ):
        """Register a db for progressive completion and run one pass.

        On a fresh db the queue is seeded with the current panel first ;
        otherwise the pass just advances the ongoing completion. `wait=True`
        runs it synchronously so the caller can read the panel data right away.
        """
        self._activate(db)
        self._run(
            db,
            wait,
            lambda b, uid: loaders.initial_load(b, uid, panel_id, progress),
        )

    def request_refresh(self, db: str, wait: bool = True, progress=None):
        """Incremental delta sync of a db (Refresh data button)."""
        self._run(db, wait, lambda b, uid: loaders.sync_store(b, uid, progress))

    def get_progress(self, db: str) -> dict:
        """Progress of the progressive load of a db (no Odoo call needed)."""
        with env.db_scope(db):
            return loaders.progress_info()

    # ---- internals -----------------------------------------------------
    def _activate(self, db: str):
        with self._lock:
            self._locks.setdefault(db, threading.Lock())
            self._active.add(db)

    def _backend(self, db: str):
        backend = self._backends.get(db)
        if backend is None:
            backend = Backend.create(db=db)
            self._backends[db] = backend
        return backend

    def _run(self, db: str, wait: bool, op):
        lock = self._locks.setdefault(db, threading.Lock())
        if wait:
            self._execute(db, lock, op)
        # even when not waiting, the background thread picks it up if active

    def _execute(self, db: str, lock, op):
        with lock:
            try:
                with env.db_scope(db):
                    backend = self._backend(db)
                    op(backend, backend.env.user.id)
            except Exception:
                logger.exception("sync failed for db %s", db)

    def _tick(self):
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            self._step()

    def _step(self):
        """One completion pass over every db that still has work."""
        with self._lock:
            active = list(self._active)
            locks = {db: self._locks[db] for db in active if db in self._locks}
        for db in active:
            lock = locks.get(db)
            if lock is None:
                continue
            more = self._complete(db, lock)
            if not more:
                with self._lock:
                    self._active.discard(db)

    def _complete(self, db: str, lock) -> bool:
        """Run one complete_store pass for a db ; False when nothing remains."""
        with lock:
            try:
                with env.db_scope(db):
                    backend = self._backend(db)
                    return bool(loaders.complete_store(backend, backend.env.user.id))
            except Exception:
                logger.exception("completion failed for db %s", db)
                return False


# module-level singleton, shared by the apps
service = SyncService()
