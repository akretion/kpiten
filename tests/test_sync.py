"""The sync : block streaming extraction, its process (lock, status, exit codes)
and the service that starts it for the dashboards."""

import polars as pl
import pytest

from kpiten_core import env, loaders, service, sync
from kpiten_core.store import DFStorage
from storage import read_df


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "data_path", str(tmp_path))
    monkeypatch.setattr(env, "current_db", "testdb")
    monkeypatch.setattr(env, "partition_size", 10)
    return tmp_path


def _pages(*id_lists):
    return [pl.DataFrame({"id": ids, "v": [f"v{i}" for i in ids]}) for ids in id_lists]


class FakeOdoo:
    """`get_sql_query` returns a tag, `_iter_sql_pages` (patched) pages by tag."""

    db = "testdb"

    def current_user_id(self):
        return 2

    def get_dataset_models(self):
        return ["sale.order"]

    def get_fields_metadata(self, model):
        return {"id": {"type": "integer"}, "v": {"type": "char"}}

    def get_sql_query(self, model, domain=None, order=""):
        return "DELTA" if domain else "FULL"


def _patch_pages(monkeypatch, full, delta, deleted=()):
    pages = {"FULL": full, "DELTA": delta}
    monkeypatch.setattr(loaders, "_pg_uri", lambda db: "uri")
    monkeypatch.setattr(loaders, "_iter_sql_pages", lambda uri, q, size: iter(pages[q]))
    monkeypatch.setattr(
        loaders, "_get_deletions", lambda uri, model, since: list(deleted)
    )


def test_sync_streams_blocks_then_applies_deltas_and_deletions(data, monkeypatch):
    # pages of 8 ids cross the block boundaries (10, 20) : a block is only
    # written once complete, and one page can feed two blocks
    _patch_pages(
        monkeypatch,
        full=_pages(range(1, 9), range(9, 17), range(17, 25)),
        delta=_pages([12, 30]),
        deleted=[3],
    )
    seen = []
    counts = loaders.sync_store(FakeOdoo(), 2, lambda *a: seen.append(a))
    assert counts == {"sale.order": 24}
    assert seen[0][:2] == ("sale.order", "full") and seen[-1][2] == 24
    assert DFStorage.is_partitioned("sale.order")
    assert read_df("sale.order")["id"].to_list() == list(range(1, 25))

    counts = loaders.sync_store(FakeOdoo(), 2)  # second run : delta
    assert counts == {"sale.order": 2}
    out = read_df("sale.order")
    assert 3 not in out["id"].to_list() and 30 in out["id"].to_list()
    assert out["id"].to_list() == sorted(out["id"].to_list())


def test_sync_migrates_a_legacy_single_file_with_a_full_extraction(data, monkeypatch):
    (data / "testdb").mkdir()
    pl.DataFrame({"id": [1], "v": ["old"]}).write_parquet(
        f"{data}/testdb/sale.order.parquet"
    )
    DFStorage.write_meta("sale.order", {"last_sync": "2026-01-01 00:00:00"})
    _patch_pages(monkeypatch, full=_pages([1, 2]), delta=_pages([9]))
    # a legacy table has no blocks to apply a delta to : full, whatever last_sync says
    assert loaders.sync_store(FakeOdoo(), 2) == {"sale.order": 2}
    assert read_df("sale.order")["v"].to_list() == ["v1", "v2"]


def test_last_sync_is_the_start_of_the_extraction(data, monkeypatch):
    """A record written while a long extraction runs must be re-read by the
    next delta, so last_sync is taken before reading, not after."""
    _patch_pages(monkeypatch, full=_pages([1]), delta=[])
    clock = iter(["2026-01-01 10:00:00", "2026-01-01 10:30:00"])
    monkeypatch.setattr(DFStorage, "now", staticmethod(lambda: next(clock)))
    loaders.sync_store(FakeOdoo(), 2)
    assert DFStorage.last_sync("sale.order") == "2026-01-01 10:00:00"


# --- the process -----------------------------------------------------------


@pytest.fixture
def fake_sync(data, monkeypatch):
    calls = []

    def sync_store(backend, uid, progress, full=False):
        calls.append(full)
        progress("sale.order", "full", 100, 100, 100)
        return {"sale.order": 100}

    monkeypatch.setattr(sync.Backend, "create", lambda db=None: FakeOdoo())
    monkeypatch.setattr(sync.loaders, "sync_store", sync_store)
    return calls


def test_run_writes_its_status(fake_sync):
    assert sync.run("testdb", full=True) == {"sale.order": 100}
    assert fake_sync == [True]
    status = sync.read_status("testdb")
    assert status["state"] == "done" and status["counts"] == {"sale.order": 100}
    assert status["model"] == "sale.order" and status["rows"] == 100
    assert not sync.is_running("testdb")


def test_a_failed_sync_says_so_and_raises(data, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("odoo is down")

    monkeypatch.setattr(sync.Backend, "create", boom)
    with pytest.raises(RuntimeError):
        sync.run("testdb")
    status = sync.read_status("testdb")
    assert status["state"] == "failed" and "odoo is down" in status["error"]
    assert not sync.is_running("testdb")  # the lock is released


def test_two_syncs_of_a_database_never_overlap(fake_sync):
    with sync._lock("testdb"):
        assert sync.is_running("testdb")
        with pytest.raises(sync.SyncBusy):
            sync.run("testdb")
        assert sync.main(["--db", "testdb"]) == sync.EXIT_BUSY
    assert sync.main(["--db", "testdb"]) == sync.EXIT_OK
    assert fake_sync == [False]  # the busy runs never reached the sync


# --- the service -----------------------------------------------------------


def test_service_relays_only_the_running_sync_of_its_child(fake_sync, data):
    seen = []
    progress = lambda *args: seen.append(args)
    relay = service.SyncService._relay

    sync._write_status("testdb", {"state": "done", "pid": 1, "model": "old", "rows": 9})
    assert relay("testdb", progress, None, 42) is None  # last run, finished
    sync._write_status(
        "testdb", {"state": "running", "pid": 7, "model": "x", "rows": 1}
    )
    assert relay("testdb", progress, None, 42) is None  # somebody else's sync
    status = {"state": "running", "pid": 42, "model": "sale.order", "mode": "full"}
    sync._write_status("testdb", {**status, "rows": 50, "count": 50, "page_size": 50})
    key = relay("testdb", progress, None, 42)
    assert seen == [("sale.order", "full", 50, 50, 50)]
    assert relay("testdb", progress, key, 42) == key and len(seen) == 1  # once


def test_service_waits_for_a_sync_started_elsewhere(data, monkeypatch):
    """The child exits busy (a cron sync holds the lock) : the front waits for
    that sync instead of failing or starting a second one."""

    class Child:
        returncode = sync.EXIT_BUSY

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return self.returncode

    running = iter([True, True, False])
    monkeypatch.setattr(service.subprocess, "Popen", Child)
    monkeypatch.setattr(service.sync, "is_running", lambda db: next(running))
    monkeypatch.setattr(service, "POLL_SECONDS", 0)
    service.SyncService().request_refresh("testdb")
    assert list(running) == []  # waited until the lock was free


# --- read ahead -----------------------------------------------------------


def test_read_ahead_keeps_the_order_and_reads_in_advance():
    import threading

    read = []

    def pages():
        for i in range(5):
            read.append(i)
            yield i

    it = loaders._read_ahead(pages(), depth=1)
    assert next(it) == 0
    # the reader did not wait for the consumer : the next page is already read
    for _ in range(100):
        if len(read) >= 2:
            break
        threading.Event().wait(0.01)
    assert len(read) >= 2
    assert [0, *it] == [0, 1, 2, 3, 4]


def test_read_ahead_raises_the_error_of_the_reading_in_the_consumer():
    def pages():
        yield 1
        raise RuntimeError("postgres went away")

    it = loaders._read_ahead(pages())
    assert next(it) == 1
    with pytest.raises(RuntimeError, match="postgres went away"):
        next(it)


def test_read_ahead_thread_stops_when_the_consumer_gives_up():
    import threading

    def endless():
        while True:
            yield 1

    it = loaders._read_ahead(endless())
    next(it)
    it.close()  # e.g. the normalization of a block failed
    for _ in range(100):
        if not [t for t in threading.enumerate() if t.name == "kpiten-read-ahead"]:
            break
        threading.Event().wait(0.05)
    assert not [t for t in threading.enumerate() if t.name == "kpiten-read-ahead"]
