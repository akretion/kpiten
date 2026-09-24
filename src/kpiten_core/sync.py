"""The parquet sync, as a process of its own.

    python -m kpiten_core.sync --db big          # incremental (cron / systemd timer)
    python -m kpiten_core.sync --db big --full   # rebuild every table

A sync reads a whole database through Postgres : it is the heavy part of the
stack. Run inside a dashboard it competes with the users for memory and a
crash takes the dashboard down with it. As its own process it can be
scheduled (cron, systemd timer), and the dashboards only read the parquets ;
the "Refresh data" button starts this same process (see `service`) instead of
syncing in-process.

Two syncs of a database never run at the same time, whoever starts them : the
process holds an exclusive lock file for its whole run (exit code 2 when it
is already held). Its progress is written to a status file the dashboards
poll.

Exit codes : 0 done, 1 failed, 2 another sync of that database is running.
"""

import argparse
import contextlib
import fcntl
import json
import logging
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

from kpiten_core import env, loaders
from kpiten_core.backend import Backend
from kpiten_core.store import DFStorage

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_FAILED, EXIT_BUSY = 0, 1, 2

# minimum seconds between two status file writes (one per page otherwise)
STATUS_EVERY = 0.25


class SyncBusy(Exception):
    """Another sync of this database holds the lock."""


def _file(db: str, name: str) -> pathlib.Path:
    with env.db_scope(db):
        directory = pathlib.Path(DFStorage.directory())
    directory.mkdir(exist_ok=True, parents=True)
    return directory / name


def log_path(db: str) -> pathlib.Path:
    return _file(db, ".sync.log")


@contextlib.contextmanager
def _lock(db: str):
    """Exclusive lock of the database's sync, or SyncBusy."""
    with open(_file(db, ".sync.lock"), "w") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncBusy(db) from None
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def is_running(db: str) -> bool:
    """Whether a sync of `db` is running right now (in any process)."""
    try:
        with _lock(db):
            return False
    except SyncBusy:
        return True


def read_status(db: str) -> dict:
    """Last status written by a sync of `db` (empty when there never was one) :
    state (running | done | failed), model, mode, rows, count, page_size,
    started, updated, error."""
    try:
        return json.loads(_file(db, ".sync-status.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _write_status(db: str, status: dict):
    status["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = _file(db, ".sync-status.json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status))
    os.replace(tmp, path)


def run(db: str, full: bool = False) -> dict[str, int]:
    """Sync `db` in this process. Returns the rows written per model.

    Raises SyncBusy when another sync of `db` is running.
    """
    with _lock(db):
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        status = {"state": "running", "pid": os.getpid(), "started": started}
        _write_status(db, status)
        last_write = [0.0]

        def progress(model, mode, offset, count, page_size):
            new_model = status.get("model") != model
            status.update(model=model, mode=mode, rows=offset, count=count)
            status["page_size"] = page_size
            if new_model or time.monotonic() - last_write[0] >= STATUS_EVERY:
                last_write[0] = time.monotonic()
                _write_status(db, status)

        try:
            with env.db_scope(db):
                backend = Backend.create(db=db)
                counts = loaders.sync_store(
                    backend, backend.current_user_id(), progress, full=full
                )
        except BaseException as err:
            status.update(state="failed", error=f"{type(err).__name__}: {err}")
            _write_status(db, status)
            raise
        status.update(state="done", counts=counts)
        _write_status(db, status)
        return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kpiten-sync", description="Sync the kpiten parquets of an Odoo database"
    )
    parser.add_argument("--db", default=env.get("ODOO_DB"), help="Odoo database")
    parser.add_argument("--full", action="store_true", help="rebuild every table")
    parser.add_argument("--data-path", help="parquet root (default : DATA_PATH)")
    args = parser.parse_args(argv)
    if not args.db:
        parser.error("no database : pass --db or set ODOO_DB")
    if args.data_path:
        env.data_path = args.data_path
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        counts = run(args.db, full=args.full)
    except SyncBusy:
        logger.warning("a sync of %s is already running", args.db)
        return EXIT_BUSY
    except Exception:
        logger.exception("sync of %s failed", args.db)
        return EXIT_FAILED
    logger.info("sync of %s done : %s", args.db, counts)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
