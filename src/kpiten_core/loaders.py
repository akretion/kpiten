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
import re
import queue
import threading
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
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
    uri = _pg_uri(backend.db)
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
    domain: list | None = None,
) -> int:
    """Full extract of one model straight from Postgres, block by block ; with
    `domain`, its records that match it only (the recent ones,
    `_extract_recent_model`).

    Each block is written as soon as it is complete, so the memory used is one
    block, not the table. The table only becomes readable as blocks once all of
    them are written (`DFStorage.commit_full`). Returns the number of rows.
    """
    logger.info("extracting %s via direct SQL %s", model, domain or "")
    metadata = backend.get_fields_metadata(model)
    if domain:
        base_query = backend.get_sql_query(model, domain, "")
    elif env.extract_mode == "view":
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


# A fresh table : its last RECENT_DAYS first (the dashboards open on 90 days), a
# result in a moment ; then its history, BACKFILL_DAYS more at each sync (every 5
# minutes, `service.keep_backfilling`) down to its first record. By their creation
# date, not by id ranges : the ids of imported records do not follow their dates. The
# table says where it is : `backfill_since`, the records created since are loaded.
RECENT_DAYS = 90
BACKFILL_DAYS = 91


def _sql_value(backend: "Backend", query: str):
    """The single value of an aggregate `query` on Postgres."""
    import connectorx as cx

    df = cx.read_sql(_pg_uri(backend.db), query, return_type="polars")
    return df[df.columns[0]][0] if df.height else None


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _newest_created(backend: "Backend", model: str, before: datetime | None = None):
    """The `create_date` of the newest record (created before `before`), None when
    there is none."""
    domain = [("create_date", "<", _stamp(before))] if before else []
    query = backend.get_sql_query(model, domain, "")
    return _sql_value(backend, f"SELECT max(create_date) FROM ({query}) AS kt_q")


def _loaded_since(model: str) -> datetime | None:
    """The date the history of a table reaches while it loads, None when complete."""
    loaded = DFStorage.read_meta(model).get("backfill_since")
    return datetime.strptime(loaded, "%Y-%m-%d %H:%M:%S") if loaded else None


def _extract_recent_model(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    progress: ProgressFn | None,
    since: datetime,
) -> int:
    """A fresh table : its records created since `since` (the same date for every
    table of the store), readable at once ; the older ones come later
    (`_backfill_model`). A table without records since then (inactive) or read from a
    view : all of it at once."""
    recent = env.extract_mode != "view" and _newest_created(backend, model)
    if not recent or recent < since:
        return _extract_full_model(backend, model, extraction_uid, progress)
    domain = [("create_date", ">=", _stamp(since))]
    rows = _extract_full_model(backend, model, extraction_uid, progress, domain)
    if rows and _newest_created(backend, model, since) is not None:
        meta = DFStorage.read_meta(model)
        meta["backfill_since"] = _stamp(since)
        DFStorage.write_meta(model, meta)
    return rows


def _history_target(backend: "Backend", models: list[str]) -> datetime | None:
    """The date the tables whose history loads all reach at this sync, the same for
    all (the parquets stay consistent : a line and its order are there together) :
    BACKFILL_DAYS before the least advanced one, a period without any record in any
    of them skipped. None when none is loading."""
    loading = {m: s for m in models if (s := _loaded_since(m))}
    if not loading:
        return None
    newest = [_newest_created(backend, m, s) for m, s in loading.items()]
    newest = [n for n in newest if n is not None]
    start = max(loading.values())
    if newest:
        start = min(start, max(newest))
    return start - timedelta(days=BACKFILL_DAYS)


def _backfill_model(
    backend: "Backend",
    model: str,
    target: datetime,
    progress: ProgressFn | None = None,
) -> int:
    """One step of the history of a table not complete yet : its records created
    from `target` (`_history_target`) to the date it reached, upserted in their
    blocks. Returns the number of rows."""
    loaded = _loaded_since(model)
    if not loaded:
        return 0
    rows = 0
    if target < loaded:
        domain = [
            ("create_date", ">=", _stamp(target)),
            ("create_date", "<", _stamp(loaded)),
        ]
        query = backend.get_sql_query(model, domain, "")
        metadata = backend.get_fields_metadata(model)
        for _, df in _stream_blocks(
            backend, query, metadata, model, "history", progress
        ):
            rows += DFStorage.merge_df(model, df)
    meta = DFStorage.read_meta(model)  # merge_df wrote its columns in it
    if _newest_created(backend, model, min(target, loaded)) is None:
        meta.pop("backfill_since", None)  # the whole history is there
        logger.info("history of %s complete", model)
    else:
        meta["backfill_since"] = _stamp(min(target, loaded))
    DFStorage.write_meta(model, meta)
    return rows


def backfill_since() -> datetime | None:
    """The date the history of the store reaches while it is loading (its oldest
    record loaded, on the table that is the least far) ; None when it is complete."""
    dates = [
        DFStorage.read_meta(table).get("backfill_since")
        for table in DFStorage.list_table_names()
    ]
    dates = [d for d in dates if d]
    if not dates:
        return None
    return datetime.strptime(max(dates), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


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
    """Most recent last_sync across the stored tables, as the user reads a date and a
    time (`user_datetime`)."""
    syncs = [DFStorage.last_sync(table) for table in DFStorage.list_table_names()]
    syncs = [s for s in syncs if s]
    if not syncs:
        return None
    dt = datetime.strptime(max(syncs), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return user_datetime(backend, user_id, dt)


def user_datetime(
    backend: "Backend", user_id: int, dt: datetime, date: bool = True, time: bool = True
) -> str:
    """`dt` (aware) in the timezone of the user and in the formats of their language
    in Odoo (`res.lang`), to the minute ; the time only without `date`, the date only
    without `time`. « UTC » after a time when the user has no timezone."""
    tz = backend.get_user_tz(user_id)
    if tz:
        try:
            dt = dt.astimezone(ZoneInfo(tz))
        except Exception:
            logger.warning("unknown timezone %s, falling back to UTC", tz)
            tz = None
    if not tz:
        dt = dt.astimezone(timezone.utc)
    date_format, time_format = backend.get_lang_formats(backend.get_user_lang(user_id))
    # to the minute : the seconds of the format of the language left out
    time_format = time_format.replace(":%S", "").replace("%S", "").strip()
    if not time:
        return dt.strftime(date_format)
    stamp = dt.strftime(f"{date_format} {time_format}" if date else time_format)
    return stamp if tz else f"{stamp} UTC"


def is_stale() -> bool:
    """Whether the most recent sync of the store is older than `DATA_STALE_HOURS` (24 by
    default) : the fronts show its date in orange. False without any sync."""
    syncs = [DFStorage.last_sync(table) for table in DFStorage.list_table_names()]
    syncs = [s for s in syncs if s]
    if not syncs:
        return False
    last = datetime.strptime(max(syncs), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    age = datetime.now(timezone.utc) - last
    return age.total_seconds() > env.data_stale_hours * 3600


def sync_store(
    backend: "Backend",
    extraction_uid: int,
    progress: ProgressFn | None = None,
    full: bool = False,
) -> dict[str, int]:
    """Incremental refresh : full extract on first run, delta afterwards.

    Per table :
    - `full` : full extract
    - no stored blocks yet (fresh database, a table still in the legacy
      single-file layout) : its records of the last RECENT_DAYS, the older ones
      BACKFILL_DAYS at each following sync (`_backfill_model`), the same dates for
      every table
    - otherwise new / updated records (`create_date`/`write_date` >
      last_sync) are normalized and upserted in their blocks, and deletions
      recorded by the `auditlog` module are applied

    Returns the rows written per model (deletions not counted).
    """
    counts: dict[str, int] = {}
    uri = _pg_uri(backend.db)
    models = backend.get_dataset_models()
    # the same dates for every table (the parquets stay consistent) : a fresh table
    # starts at `recent`, the tables whose history loads all reach `target`
    recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=RECENT_DAYS
    )
    target = None if full else _history_target(backend, models)
    for model in models:
        since = (
            None
            if full or not DFStorage.is_partitioned(model)
            else DFStorage.last_sync(model)
        )
        if full:
            counts[model] = _extract_full_model(
                backend, model, extraction_uid, progress
            )
            continue
        if not since:  # a fresh table : its recent records first
            counts[model] = _extract_recent_model(
                backend, model, extraction_uid, progress, recent
            )
            continue
        started = (
            DFStorage.now()
        )  # before reading : a write during the sync is re-read next time
        counts[model] = _extract_delta_model(backend, model, since, progress)
        _apply_deletions(uri, model, since)
        DFStorage.touch_sync(model, started)
        if target is not None:  # a table whose history is loading : to `target`
            counts[model] += _backfill_model(backend, model, target, progress)
    return counts


def load_store() -> dict[str, pl.LazyFrame]:
    """Lazy scans of every stored table, WITHOUT any user restriction.

    Not for serving users (no column ACL, no record rules, no language) :
    use `user_store`. Meant for admin scripts and tests.
    """
    return {table: DFStorage.scan_df(table) for table in DFStorage.list_table_names()}


FROM_TABLE_RE = re.compile(r'\bFROM\s+"(\w+)"')


def _all_readable(backend: "Backend", query: str) -> tuple[int, int] | None:
    """(the highest id, the number of rows) of the table when the access `query`
    keeps all its rows, else None.

    The record rules let a manager read every row : the ids are then all the ids
    of the table, millions on a big base, fetched for nothing. Looking for a
    hidden row is cheaper : it stops at the first one (a salesman, ~10 ms), and
    goes through the table only when there is none. One statement, one snapshot.
    """
    table = FROM_TABLE_RE.search(query)
    if not table:
        return None
    import connectorx as cx

    row = cx.read_sql(
        _pg_uri(backend.db),
        # counting the table in a CASE, only when no row is hidden, makes Postgres
        # lose its parallel plan : the count is ~80 ms on 3 million rows
        f"""SELECT NOT EXISTS (
                SELECT 1 FROM "{table.group(1)}" AS kt_t WHERE NOT EXISTS (
                    SELECT 1 FROM ({query}) AS kt_r WHERE kt_r.id = kt_t.id
                )
            ) AS all_rows, max(id) AS max_id, count(*) AS total
        FROM "{table.group(1)}"
        """,
        return_type="polars",
    ).row(0, named=True)
    if not row["all_rows"]:
        return None
    return row["max_id"] or 0, row["total"]


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


def user_rows(backend: "Backend", table: str, user_id: int, lazy: pl.LazyFrame):
    """`lazy` restricted to the rows of `table` the user may read (record rules).

    Odoo builds the `SELECT id` with its own record rules (ir.rule) applied for
    that user ; it is run here straight against Postgres, like the extraction.

    When the rules keep every row, `id <= max(id)` is the same restriction as
    the ids (`_all_readable`) : the rows synced later have a greater id and stay
    hidden. Only if the stored rows up to that id are as many as in Postgres : a
    record deleted since the last sync is still stored, and might be one the
    rules would hide ; the ids then.
    """
    query = backend.get_access_query(table, user_id)
    if not query:  # no read access to the model at all
        return lazy.filter(pl.lit(False))
    everything = _all_readable(backend, query)
    if everything is not None:
        max_id, total = everything
        bounded = lazy.filter(pl.col("id") <= max_id)
        if bounded.select(pl.len()).collect().item() == total:
            return bounded
    return restrict_rows(lazy, _read_sql_df(_pg_uri(backend.db), query)["id"])


def user_store(backend: "Backend", user_id: int) -> "UserStore":
    """Per-user view of the store : the columns the user may read (ACL), the
    rows the user may read (record rules), translatable lang.

    The tables are lazy scans of the parquets : the session holds a query
    plan (plus the ids the user may read), not the data. A tile reads what
    it needs when it runs.

    The record rules are always applied, even for a user who may read every
    row : rows synced after a table is opened are not in its ids (nor under its
    id bound, `_all_readable`), so they stay hidden until the store is rebuilt,
    instead of leaking to a user who may not read them.

    A table is opened (its columns, its rows) the first time it is read
    (`UserStore`) : a panel pays for the tables its tiles read, not for all.
    """
    lang = backend.get_user_lang(user_id)

    def open_table(table: str) -> pl.LazyFrame:
        with env.db_scope(backend.db):
            allowed = backend.get_allowed_fields(table, user_id)
            lazy = DFStorage.scan_df(table, allowed_fields=allowed, lang=lang)
            return user_rows(backend, table, user_id, lazy)

    with env.db_scope(backend.db):
        return UserStore(DFStorage.list_table_names(), open_table)


class UserStore(Mapping):
    """The tables of a user (name -> LazyFrame), each opened the first time it is
    read, once : the record rules of a table cost a query on Postgres, up to
    seconds on a big base, a panel reads a few tables of the store.

    `store | {name: frame}` is a store with those frames on top (the derived
    tables, a table narrowed by a filter), the opened tables shared.

    A table whose access could not be resolved has no row and no column : the
    user sees nothing of it rather than everything.
    """

    def __init__(self, names, open_table, frames=None, opened=None, lock=None):
        self._names = list(names)
        self._open_table = open_table
        self._frames = dict(frames or {})  # set on top, a derived table...
        self._opened = {} if opened is None else opened  # shared by the copies
        self._lock = lock or threading.Lock()

    def __getitem__(self, name):
        if name in self._frames:
            return self._frames[name]
        if name not in self._names:
            raise KeyError(name)
        with self._lock:  # the tiles of a panel may run in threads
            if name not in self._opened:
                try:
                    self._opened[name] = self._open_table(name)
                except Exception:
                    logger.exception("user store fetch failed for %s", name)
                    self._opened[name] = pl.LazyFrame()
            return self._opened[name]

    def __iter__(self):
        yield from self._names
        yield from (name for name in self._frames if name not in self._names)

    def __len__(self):
        return len(set(self._names) | set(self._frames))

    def __contains__(self, name):
        return name in self._frames or name in self._names

    def __or__(self, frames):
        return UserStore(
            self._names,
            self._open_table,
            {**self._frames, **frames},
            self._opened,
            self._lock,
        )

    def __setitem__(self, name, frame):
        self._frames[name] = frame

    def pop(self, name, *default):
        return self._frames.pop(name, *default)


def tile_store(backend: "Backend", user_id: int) -> "UserStore":
    """The store of the tiles : `user_store`, and the shared derived tables
    (`kt.derived.table`) computed on it. A tile reads a derived table by its name
    (`from = "confirmed_sales"`, or in the SQL of a `data` tile) ; each user sees their
    own rows. A personal derived table is not here : the tiles of a panel are seen by
    several users."""
    from kpiten_core import derived

    store = user_store(backend, user_id)
    shared = [d for d in backend.get_derived_tables(user_id) if d.get("shared")]
    tables, errors = derived.resolve(store, shared)
    for name, why in errors.items():
        logger.warning("derived table %s left out for user %s : %s", name, user_id, why)
    return store | tables
