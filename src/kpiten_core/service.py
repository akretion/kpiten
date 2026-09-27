"""Parquet sync service (kpiten-core), for the dashboard fronts.

The fronts (shiny / nicegui) ask for a sync on demand (the "Refresh data"
button, or an empty database on first load). The sync itself is heavy, so it
never runs inside the front : `request_refresh(db)` starts `kpiten_core.sync`
as a child process and waits for it, relaying its progress. A crash or an
out-of-memory kill then only takes the child down, and the same process can
be run from cron (`python -m kpiten_core.sync --db ...`) so that the fronts
find the data already fresh.

One child at a time per database from a front (a per-db lock, so two users
clicking "Refresh" share one sync) ; across processes the sync's own lock file
does the same : a front that finds a sync already running waits for it.
"""

import logging
import subprocess
import sys
import threading
import time

from kpiten_core import env, sync

logger = logging.getLogger(__name__)

POLL_SECONDS = 0.5
# how long a front waits for a sync started elsewhere (cron, another front)
WAIT_OTHER_SECONDS = 3600
# the syncs a user asks for run on the next boundary of these slots of the clock
# (asked at 10:02 : run at 10:05) ; all the requests of a slot share one sync
SLOT_SECONDS = 300


def next_slot(now: float | None = None) -> float:
    """The time (epoch seconds) of the next slot boundary, `now` itself when it is
    one."""
    now = time.time() if now is None else now
    return -(-now // SLOT_SECONDS) * SLOT_SECONDS


class SyncService:
    def __init__(self):
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._done: dict[str, float] = {}  # db -> the last slot synced
        self._backfilling: set[str] = set()  # the dbs whose history is loading

    def keep_backfilling(self, db: str):
        """While the history of `db` is loading (`loaders.backfill_since`) : a sync
        at every slot, in a thread of its own (one per db, whoever asks) ; it stops
        when the history is complete."""
        with self._lock:
            if db in self._backfilling or not self._history_loading(db):
                return
            self._backfilling.add(db)

        def loop():
            try:
                while self._history_loading(db):
                    self.scheduled_refresh(db, next_slot())
            except Exception:
                logger.exception("the history of db %s stops loading", db)
            finally:
                with self._lock:
                    self._backfilling.discard(db)

        threading.Thread(target=loop, name=f"kpiten-history-{db}", daemon=True).start()

    @staticmethod
    def _history_loading(db: str) -> bool:
        from kpiten_core import loaders

        with env.db_scope(db):
            return loaders.backfill_since() is not None

    def scheduled_refresh(self, db: str, slot: float) -> bool:
        """A sync asked by a user (the Refresh button) : at `slot` (`next_slot`),
        once for all the requests of that slot. Blocks until it is over ; False when
        an other request of the slot already did it."""
        time.sleep(max(0.0, slot - time.time()))
        with self._db_lock(db):
            if self._done.get(db, 0) >= slot:
                return False
            self._execute(db, None, False)
            self._done[db] = slot
        return True

    def request_refresh(self, db: str, progress=None, full: bool = False):
        """Sync `db` (incremental unless `full`), in a child process. Returns
        when the sync is over. `progress(model, mode, offset, count, page_size)`
        is called while it runs, from the calling thread."""
        with self._db_lock(db):
            self._execute(db, progress, full)

    def _db_lock(self, db: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(db, threading.Lock())

    def _execute(self, db: str, progress, full: bool):
        cmd = [sys.executable, "-m", "kpiten_core.sync", "--db", db]
        cmd += ["--data-path", env.data_path]
        if full:
            cmd.append("--full")
        with open(sync.log_path(db), "w") as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            seen = None
            while child.poll() is None:
                seen = self._relay(db, progress, seen, child.pid)
                time.sleep(POLL_SECONDS)
        if child.returncode == sync.EXIT_BUSY:
            self._wait_other(db, progress)
        elif child.returncode != sync.EXIT_OK:
            logger.error(
                "sync of db %s failed (exit %s), see %s",
                db,
                child.returncode,
                sync.log_path(db),
            )

    def _wait_other(self, db: str, progress):
        """A sync started elsewhere holds the lock : wait for it to finish."""
        logger.info("a sync of db %s is already running : waiting for it", db)
        seen = None
        deadline = time.monotonic() + WAIT_OTHER_SECONDS
        while sync.is_running(db) and time.monotonic() < deadline:
            seen = self._relay(db, progress, seen)
            time.sleep(POLL_SECONDS)

    @staticmethod
    def _relay(db: str, progress, seen, pid: int | None = None):
        """Hand the running sync's latest progress to the front (each step
        once). With `pid`, only that process' : the status file may still hold
        the last run of an earlier one."""
        status = sync.read_status(db)
        if status.get("state") != "running" or (pid and status.get("pid") != pid):
            return seen
        key = (status.get("model"), status.get("rows"))
        if progress and status.get("model") and key != seen:
            progress(
                status["model"],
                status.get("mode", ""),
                status.get("rows", 0),
                status.get("count", 0),
                status.get("page_size", 0),
            )
        return key


# module-level singleton, shared by the apps
service = SyncService()
