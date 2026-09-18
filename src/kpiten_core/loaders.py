"""Framework-agnostic store loaders (extract / parquet / per-user views).

Shared by the dashboard apps (shiny, nicegui...): builds the parquet
snapshot from Odoo and returns per-user column-filtered dataframes.

Extraction always streams straight from Postgres with connectorx
(`EXTRACT_MODE = sql | view`), bypassing the Odoo ORM/RPC entirely for the
bulk data. The rows are read by pages of increasing id and stored block by
block (`DFStorage`, PARTITION_SIZE ids per block) : a sync never holds more
than one block, whatever the size of the table. `sync_store` refreshes the
parquets incrementally : only records created or written since the last sync
are re-extracted (upsert into the blocks they belong to), and deletions are
applied from the `auditlog` module (unlink logs).
"""

import logging
import queue
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

import polars as pl

from kpiten_core import env, resolve
from kpiten_core.dfnorm import Df
from kpiten_core.store import ColumnOrder, DFStorage

if TYPE_CHECKING:
    from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)

# Progress callback : (model, mode, offset, count, page_size)
ProgressFn = Callable[[str, str, int, int, int], None]


def _pg_uri(db: str | None) -> str:
    """Postgres connection URI for a database (default = scoped db)."""
    database = env.pg_db or db or env.active_db() or ""
    return (
        f"postgresql://{env.pg_user}:{env.pg_pwd}"
        f"@{env.pg_host}:{env.pg_port}/{database}"
    )


def _read_sql_df(uri: str, query: str) -> "pl.DataFrame":
    """Run `query` against Postgres into a polars DataFrame (connectorx)."""
    import connectorx as cx

    df = cx.read_sql(uri, query, return_type="polars")
    # connectorx reads odoo integer PKs as Int32 ; normalize to Int64
    return df.with_columns(pl.col("id").cast(pl.Int64))


def _iter_sql_pages(uri: str, base_query: str, page_size: int):
    """Yield `base_query`'s rows by bounded pages, keyset-paginated on id.

    `base_query` is wrapped so its own ORDER BY (if any) is irrelevant : id is
    the model's primary key, so ordering and paging on it is always valid and
    lets Postgres use the index instead of an ever-growing OFFSET scan.
    """
    last_id = -1
    while True:
        page_query = (
            f"SELECT * FROM ({base_query}) AS kt_page "
            f"WHERE id > {last_id} ORDER BY id LIMIT {page_size}"
        )
        page = _read_sql_df(uri, page_query)
        if page.height == 0:
            return
        yield page
        last_id = int(page["id"][-1])
        if page.height < page_size:
            return


def _read_ahead(pages, depth: int = 1):
    """Iterate `pages` in a thread, up to `depth` pages ahead of the consumer.

    Reading a page is a wait on Postgres (connectorx works without the GIL)
    while a block is resolved, normalized and written by the consumer : run
    one after the other they add up, side by side the sync takes the time of
    the longer one. Memory grows by the pages in flight, `depth` + 1.

    The pages come out in order ; an error of the reading is raised to the
    consumer ; if the consumer stops early the thread is told to stop.
    """
    ahead: queue.Queue = queue.Queue(maxsize=depth)
    stop = threading.Event()
    end = object()

    def put(item) -> bool:
        while not stop.is_set():
            try:
                ahead.put(item, timeout=0.2)
                return True
            except queue.Full:
                pass
        return False

    def read():
        try:
            for page in pages:
                if not put(page):
                    return
        except BaseException as err:  # handed to the consumer
            put(err)
            return
        put(end)

    threading.Thread(target=read, name="kpiten-read-ahead", daemon=True).start()
    try:
        while True:
            item = ahead.get()
            if item is end:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()


def _normalize_block(backend: "Backend", chunks: list, metadata: dict) -> pl.DataFrame:
    """Raw rows of one block -> resolved m2o names -> normalized dataframe.

    Resolving and normalizing per block (not per page, not per table) keeps
    one batched RPC per m2o field and block, and a memory bounded by the block.
    """
    raw = pl.concat(chunks, how="vertical_relaxed")
    raw = resolve.inject_display_names(backend, raw, metadata)
    return Df(raw, fields=metadata).get_df()


def _stream_blocks(
    backend: "Backend",
    base_query: str,
    metadata: dict,
    model: str,
    mode: str,
    progress: ProgressFn | None,
):
    """Yield `(block, normalized dataframe)` for `base_query`, block by block.

    The pages come by increasing id, so the rows of a block are contiguous :
    a block is emitted as soon as the pages move on to the next one. At most
    one block (PARTITION_SIZE ids) is held at a time.
    """
    uri = _pg_uri(backend.env.db)
    chunks: list[pl.DataFrame] = []
    current = None
    total = 0
    pages = _iter_sql_pages(uri, base_query, env.sync_page_size)
    for page in _read_ahead(pages):
        total += page.height
        if progress:
            progress(model, mode, total, page.height, env.sync_page_size)
        for block, part in DFStorage.split_blocks(page):
            if current is not None and block != current:
                yield current, _normalize_block(backend, chunks, metadata)
                chunks = []
            current = block
            chunks.append(part)
    if chunks:
        yield current, _normalize_block(backend, chunks, metadata)


def _extract_full_model(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    progress: ProgressFn | None = None,
) -> int:
    """Full extract of one model straight from Postgres, block by block.

    Each block is written as soon as it is complete, so the memory used is one
    block, not the table. The table only becomes readable as blocks once all of
    them are written (`DFStorage.commit_full`). Returns the number of rows.
    """
    logger.info("extracting %s via direct SQL", model)
    metadata = backend.get_fields_metadata(model)
    if env.extract_mode == "view":
        base_query = f"SELECT * FROM {backend.get_view_name(model)}"
    else:
        base_query = backend.get_sql_query(model, [], "")
    started = DFStorage.now()
    columns = ColumnOrder()
    written: set[int] = set()
    rows = 0
    for block, df in _stream_blocks(
        backend, base_query, metadata, model, "full", progress
    ):
        DFStorage.write_block(model, block, df)
        columns.update(df)
        written.add(block)
        rows += df.height
    if not written:
        logger.warning("no records for %s", model)
        return 0
    DFStorage.commit_full(model, metadata, written, columns.order(), started)
    return rows


def _extract_delta_model(
    backend: "Backend",
    model: str,
    since: str,
    progress: ProgressFn | None = None,
) -> int:
    """Delta extract of one model straight from Postgres (write/create > since).

    Same block by block streaming as the full extract ; each block of changed
    records is upserted into the stored block it belongs to
    (`DFStorage.merge_df`), the other blocks are not touched. Returns the
    number of rows upserted.
    """
    logger.info("delta-syncing %s via direct SQL (since=%s)", model, since)
    metadata = backend.get_fields_metadata(model)
    domain = ["|", ("write_date", ">", since), ("create_date", ">", since)]
    base_query = backend.get_sql_query(model, domain, "")
    rows = 0
    for _, df in _stream_blocks(
        backend, base_query, metadata, model, "delta", progress
    ):
        rows += DFStorage.merge_df(model, df)
    return rows


def _get_deletions(uri: str, model: str, since: str) -> list[int]:
    """Ids of `model` records deleted after `since` (module `auditlog`), via SQL.

    Returns [] when auditlog isn't installed (no `auditlog_log` table) rather
    than raising.
    """
    query = (
        "SELECT al.res_id AS id FROM auditlog_log al "
        "JOIN ir_model im ON im.id = al.model_id "
        f"WHERE im.model = '{model}' AND al.method = 'unlink' "
        f"AND al.create_date > '{since}'"
    )
    try:
        df = _read_sql_df(uri, query)
    except Exception:
        return []
    return df["id"].drop_nulls().to_list() if df.height else []


def _apply_deletions(uri: str, model: str, since: str) -> int:
    deleted_ids = _get_deletions(uri, model, since)
    if not deleted_ids:
        return 0
    removed = DFStorage.delete_records(model, deleted_ids)
    logger.info("sync %s : %s records deleted", model, removed)
    return removed


def last_sync(backend: "Backend", user_id: int) -> str | None:
    """Most recent last_sync across the stored tables, in the user timezone.

    Formatted 'YYYY-MM-DD HH:MM' (minutes precision) ; UTC suffix is added
    when the user has no timezone set.
    """
    syncs = [DFStorage.last_sync(table) for table in DFStorage.list_table_names()]
    syncs = [s for s in syncs if s]
    if not syncs:
        return None
    dt = datetime.strptime(max(syncs), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    tz = backend.get_user_tz(user_id)
    if tz:
        try:
            dt = dt.astimezone(ZoneInfo(tz))
        except Exception:
            logger.warning("unknown timezone %s, falling back to UTC", tz)
            tz = None
    stamp = dt.strftime("%Y-%m-%d %H:%M")
    return stamp if tz else f"{stamp} UTC"


def build_store(
    backend: "Backend", extraction_uid: int, progress: ProgressFn | None = None
) -> dict[str, int]:
    """Full extract of every declared dataset (kt.dataset), via connectorx.

    Returns the number of rows stored per model."""
    return {
        model: _extract_full_model(backend, model, extraction_uid, progress)
        for model in backend.get_dataset_models()
    }


def sync_store(
    backend: "Backend",
    extraction_uid: int,
    progress: ProgressFn | None = None,
    full: bool = False,
) -> dict[str, int]:
    """Incremental refresh : full extract on first run, delta afterwards.

    Per table :
    - no stored blocks yet (fresh database, a table still in the legacy
      single-file layout, or `full`) : full extract
    - otherwise new / updated records (`create_date`/`write_date` >
      last_sync) are normalized and upserted in their blocks, and deletions
      recorded by the `auditlog` module are applied

    Returns the rows written per model (deletions not counted).
    """
    counts: dict[str, int] = {}
    uri = _pg_uri(backend.env.db)
    for model in backend.get_dataset_models():
        since = (
            None
            if full or not DFStorage.is_partitioned(model)
            else DFStorage.last_sync(model)
        )
        if not since:
            counts[model] = _extract_full_model(
                backend, model, extraction_uid, progress
            )
            continue
        started = (
            DFStorage.now()
        )  # before reading : a write during the sync is re-read next time
        counts[model] = _extract_delta_model(backend, model, since, progress)
        _apply_deletions(uri, model, since)
        DFStorage.touch_sync(model, started)
    return counts


def load_store() -> dict[str, pl.LazyFrame]:
    """Lazy scans of every stored table, WITHOUT any user restriction.

    Not for serving users (no column ACL, no record rules, no language) :
    use `user_store`. Meant for admin scripts and tests.
    """
    return {table: DFStorage.scan_df(table) for table in DFStorage.list_table_names()}


def accessible_ids(backend: "Backend", table: str, user_id: int) -> pl.Series:
    """Ids of the `table` records the user may read.

    Odoo builds the `SELECT id` with its own record rules (ir.rule) applied for
    that user ; it is run here straight against Postgres, like the extraction.
    """
    query = backend.get_access_query(table, user_id)
    if not query:  # no read access to the model at all
        return pl.Series("id", [], dtype=pl.Int64)
    return _read_sql_df(_pg_uri(backend.env.db), query)["id"]


def restrict_rows(frame: "pl.DataFrame | pl.LazyFrame", ids: pl.Series):
    """The rows of `frame` whose `id` is in `ids` (same kind of frame back).

    A semi join rather than `is_in` : it stays lazy, and polars can push the
    tile filters below it. `maintain_order` keeps the rows in the parquet
    order, which a join does not do by default (a pivot shows that order).
    """
    keys = ids.rename("id").to_frame()
    if isinstance(frame, pl.LazyFrame):
        keys = keys.lazy()
    return frame.join(keys, on="id", how="semi", maintain_order="left")


def user_store(backend: "Backend", user_id: int) -> dict[str, pl.LazyFrame]:
    """Per-user view of the store : the columns the user may read (ACL), the
    rows the user may read (record rules), translatable lang.

    The tables are lazy scans of the parquets : the session holds a query
    plan (plus the ids the user may read), not the data. A tile reads what
    it needs when it runs.

    The record rules are always applied, even for a user who may read every
    row : rows synced after this call are not in `ids`, so they stay hidden
    until the store is rebuilt, instead of leaking to a user who may not read
    them.

    A table whose access could not be resolved is left out : the user sees
    nothing of it rather than everything.
    """
    lang = backend.get_user_lang(user_id)
    store: dict[str, pl.LazyFrame] = {}
    with env.db_scope(backend.env.db):
        for table in DFStorage.list_table_names():
            try:
                allowed = backend.get_allowed_fields(table, user_id)
                lazy = DFStorage.scan_df(table, allowed_fields=allowed, lang=lang)
                ids = accessible_ids(backend, table, user_id)
                store[table] = restrict_rows(lazy, ids)
            except Exception:
                logger.exception("user store fetch failed for %s", table)
    return store
