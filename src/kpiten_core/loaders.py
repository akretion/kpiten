"""Framework-agnostic store loaders (extract / parquet / per-user views).

Shared by the dashboard apps (shiny, nicegui...): builds the parquet
snapshot from Odoo and returns per-user column-filtered dataframes.

`sync_store` refreshes the parquets incrementally : only records created or
written since the last sync are re-extracted (upsert), and deletions are
applied from the `auditlog` module (unlink logs).
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

import polars as pl

from kpiten_core import env, resolve
from kpiten_core.dfnorm import Df
from kpiten_core.stage import Stage
from kpiten_core.store import DFStorage

if TYPE_CHECKING:
    from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)

# Progress callback : (model, mode, offset, count, page_size)
ProgressFn = Callable[[str, str, int, int, int], None]


def _iter_chunks(
    backend: "Backend",
    model: str,
    domain: list,
    user_id: int,
    offset: int = 0,
    progress: ProgressFn | None = None,
    mode: str = "full",
):
    """Yield chunks of raw records, paginated so no RPC call is unbounded.

    `offset` lets a partial extraction resume where it stopped. Each chunk is
    one bounded search+read (see env.sync_page_size).
    """
    page = env.sync_page_size
    while True:
        raw_vals = backend.get_record_vals(
            model, domain, user_id, limit=page, offset=offset
        )
        if not raw_vals:
            return
        yield raw_vals
        if progress:
            progress(model, mode, offset, len(raw_vals), page)
        offset += len(raw_vals)


# ---- direct Postgres extraction (EXTRACT_MODE = sql | view) -----------
# The app streams the Odoo-generated SELECT straight from Postgres with
# connectorx, bypassing the ORM and the JSONL staging. The result is
# normalized by `Df` exactly like the jsonrpc path, so the parquet is
# schema-equivalent.


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
    # connectorx reads odoo integer PKs as Int32 ; normalize to Int64 to match
    # the jsonrpc extraction
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


def _extract_full_model_sql(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    progress: ProgressFn | None = None,
):
    """Full extract of one model straight from Postgres, paged by id.

    Each page is one bounded connectorx query (`env.sync_page_size` rows), so
    a single call never has to hold an arbitrarily large result in memory the
    way one unbounded query over the whole table would. Pages are normalized
    as they arrive and only concatenated once, right before the single
    parquet write.
    """
    logger.info("extracting %s via direct SQL", model)
    metadata = backend.get_fields_metadata(model)
    uri = _pg_uri(backend.env.db)
    if env.extract_mode == "view":
        base_query = f"SELECT * FROM {backend.get_view_name(model)}"
    else:
        base_query = backend.get_sql_query(model, [], "")
    chunks = []
    total = 0
    for page in _iter_sql_pages(uri, base_query, env.sync_page_size):
        page = resolve.inject_display_names(backend, page, metadata)
        chunks.append(Df(page, fields=metadata).get_df())
        total += page.height
        if progress:
            progress(model, env.extract_mode, total, page.height, env.sync_page_size)
    if not chunks:
        logger.warning("no records for %s", model)
        return {}
    norm = pl.concat(chunks, how="vertical_relaxed")
    DFStorage.store_raw(model, [], metadata, norm)
    return {model: norm}


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


def _extract_full_model(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    progress: ProgressFn | None = None,
):
    """Full extract of one model, staged as bounded JSONL chunks then
    consolidated into the parquet in a single pass (see `Stage`).

    Staging keeps memory bounded to one page at a time, and an interruption
    resumes from the chunks already on disk (`Stage.next_offset`) instead of
    re-reading and rewriting the whole growing parquet on every chunk (the
    old behaviour, quadratic on a large table like sale.order.line).
    """
    logger.info("extracting %s", model)
    metadata = backend.get_fields_metadata(model)
    offset = Stage.next_offset(backend, model)
    if offset:
        logger.info("resuming staged extract of %s at offset=%s", model, offset)
    done = False
    while not done:
        _, done = Stage.pull_batch(
            backend,
            model,
            offset,
            [],
            "",
            env.sync_batch_size,
            env.sync_page_size,
            extraction_uid,
            progress,
            mode="full",
        )
        offset = Stage.next_offset(backend, model)
    if offset == 0:
        logger.warning("no records for %s", model)
        return {}
    Stage.consolidate(backend, model, metadata)
    return {model: DFStorage.retrieve_df(model)["df"]}


def build_store(
    backend: "Backend", extraction_uid: int, progress: ProgressFn | None = None
) -> dict[str, pl.DataFrame]:
    """Extract all declared datasets (kt.dataset) and refresh parquets.

    Each model is extracted by bounded chunks (`env.sync_page_size`) so a very
    large table never times out on a single RPC call. On interruption the next
    call resumes at the saved offset instead of restarting.
    """
    store: dict[str, pl.DataFrame] = {}
    for model in backend.get_dataset_models():
        if env.extract_mode != "jsonrpc":
            store.update(
                _extract_full_model_sql(backend, model, extraction_uid, progress)
            )
            continue
        try:
            store.update(_extract_full_model(backend, model, extraction_uid, progress))
        except Exception:
            # the staged JSONL chunks are kept on disk, so the next sync
            # resumes where we stopped (see Stage.next_offset)
            logger.exception("full extract of %s interrupted", model)
            raise
    return store


def _extract_delta_model(
    backend: "Backend",
    model: str,
    since: str,
    extraction_uid: int,
    offset: int = 0,
    progress: ProgressFn | None = None,
):
    """Paginated delta extract (create/write > since), committing per chunk."""
    logger.info("syncing %s (since=%s, offset=%s)", model, since, offset)
    store: dict[str, pl.DataFrame] = {}
    domain = ["|", ("write_date", ">", since), ("create_date", ">", since)]
    for chunk in _iter_chunks(
        backend,
        model,
        domain,
        extraction_uid,
        offset=offset,
        progress=progress,
        mode="delta",
    ):
        df = DFStorage.append_records(model, chunk)
        store[model] = df
        offset += len(chunk)
        DFStorage.set_sync_state(
            model, {"mode": "delta", "offset": offset, "since": since}
        )
    return store


# ---- progressive recent->oldest load (fresh databases) ----------------
# On a first load (no parquet yet), tables are pulled by priority (current
# panel first, then other panels, then off-panel) and from the most recent
# create_date to the oldest, in bounded batches. A global `prog` queue keeps
# the completion state so background passes resume across app restarts.


def panel_model_order(backend: "Backend", panel_id: int | None) -> list[str]:
    """Priority-ordered dataset models : current panel, other panels, off-panel.

    A model shared by several panels is pulled only once, at its first rank.
    """
    panels = backend.get_panels()  # ordered by sequence, id
    ordered: list[str] = []
    seen: set[str] = set()
    uid = backend.env.user.id

    def _add_models_for(pid: int):
        for tile in backend.get_panel_tiles(pid, uid):
            model = tile["model"]
            if model not in seen:
                seen.add(model)
                ordered.append(model)

    if panel_id:
        _add_models_for(panel_id)
    for p in panels:
        if p["id"] != panel_id:
            _add_models_for(p["id"])
    for model in backend.get_dataset_models():
        if model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _pull_model_staged(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    offset: int,
    max_date: str,
    budget: int,
    progress: ProgressFn | None = None,
):
    """Stage up to `budget` records of `model`, most recent create_date first.

    Each chunk is dumped by Odoo as JSONL on the shared volume (no data over
    the wire), so an interruption only loses the in-flight chunk ; the next
    call resumes from `Stage.next_offset`. When the table is fully staged the
    chunks are consolidated into the final parquet in a single pass.

    Returns (rows_pulled, done) ; done=True when every record up to `max_date`
    has been staged.
    """
    domain = [("create_date", "<=", max_date)]
    order = "create_date desc, id desc"
    rows, done = Stage.pull_batch(
        backend,
        model,
        offset,
        domain,
        order,
        budget,
        env.sync_page_size,
        extraction_uid,
        progress,
    )
    if done:
        Stage.consolidate(backend, model, backend.get_fields_metadata(model))
    return rows, done


def initial_load(
    backend: "Backend",
    extraction_uid: int,
    panel_id: int | None = None,
    progress: ProgressFn | None = None,
):
    """Set up the priority queue and pull the first batch (fresh database).

    Current panel tables come first, so they are pulled (and completed) before
    the others ; the background `complete_store` continues filling the older
    data without overloading Odoo.

    In direct-SQL mode (`EXTRACT_MODE = sql`/`view`) the whole store is pulled
    in one streamed pass : no recent->oldest background needed, so we extract
    everything and mark each table as synced.
    """
    if env.extract_mode != "jsonrpc":
        store = build_store(backend, extraction_uid, progress)
        for model in store:
            DFStorage.touch_sync(model)
        return store
    prog = DFStorage.get_prog()
    if not prog:
        # only seed the queue when nothing has ever been started for this db
        DFStorage.set_prog(
            {"order": panel_model_order(backend, panel_id), "current": None}
        )
    complete_store(backend, extraction_uid, progress)


def complete_store(
    backend: "Backend",
    extraction_uid: int,
    progress: ProgressFn | None = None,
) -> bool:
    """Pull one batch, advancing the completion queue.

    Returns True while more data remains to be loaded, False when every table
    is fully loaded. Each call pulls up to `env.sync_batch_size` records.
    """
    prog = DFStorage.get_prog()
    order = prog.get("order", [])
    current = prog.get("current") or {}
    model = current.get("model")
    if not model and not order:
        return False
    if not model:
        model = order.pop(0)
        current = {"model": model, "offset": 0}
    max_date = current.get("max_date")
    if not max_date:
        max_date = backend.get_max_create_date(model, extraction_uid)
        if not max_date:
            # empty table : nothing to pull
            DFStorage.set_prog({"order": order, "current": None})
            return bool(order)
        current["max_date"] = max_date
    # count once so the front can report a reliable % without a full scan
    if "total" not in current:
        current["total"] = backend.get_count(
            model, [("create_date", "<=", max_date)], extraction_uid
        )
    offset = Stage.next_offset(backend, model)
    rows, done = _pull_model_staged(
        backend, model, extraction_uid, offset, max_date, env.sync_batch_size, progress
    )
    if done:
        # table fully loaded : mark last_sync so delta syncs take over
        DFStorage.touch_sync(model)
        current = {}
    else:
        current = {
            "model": model,
            "offset": offset + rows,
            "max_date": max_date,
            "total": current["total"],
        }
    DFStorage.set_prog({"order": order, "current": current or None})
    return bool(order) or bool(current)


def pending_tables() -> set[str]:
    """Models still being progressively loaded (partial parquet)."""
    return DFStorage.partial_tables()


def progress_info() -> dict:
    """Progress of the ongoing progressive load, read from the stored state.

    Returns :
    - `current` : the table being imported, with its offset/total and percent,
      or None when nothing is in flight.
    - `queued`  : tables not started yet (still to import), in priority order.
    """
    prog = DFStorage.get_prog()
    order = prog.get("order", [])
    current = prog.get("current") or {}
    model = current.get("model")
    info = {"current": None, "queued": list(order)}
    if model:
        total = current.get("total", 0)
        offset = current.get("offset", 0)
        percent = round(offset / total * 100) if total else 0
        info["current"] = {
            "model": model,
            "offset": offset,
            "total": total,
            "percent": percent,
        }
    return info


def sync_store(
    backend: "Backend", extraction_uid: int, progress: ProgressFn | None = None
) -> dict[str, pl.DataFrame]:
    """Incremental refresh : full extract on first run, delta afterwards.

    Per table :
    - new / updated records (`create_date`/`write_date` > last_sync) are
      normalized and upserted in the parquet
    - deletions recorded by the `auditlog` module are applied

    Extraction is paginated and resumable, so a very large delta (or a very
    large first extract) never times out : on interruption the next call
    resumes at the saved offset.
    """
    store: dict[str, pl.DataFrame] = {}
    partial = DFStorage.partial_tables()
    for model in backend.get_dataset_models():
        if model in partial:
            # still being progressively loaded (recent->oldest) : the
            # background completion handles it, skip the delta here
            continue
        state = DFStorage.get_sync_state(model)
        last_sync = DFStorage.last_sync(model)
        if state:
            # resume an interrupted delta extraction (a full extract resumes
            # on its own from the staged JSONL chunks, see Stage.next_offset)
            offset = state["offset"]
            since = state.get("since") or last_sync
            try:
                store.update(
                    _extract_delta_model(
                        backend, model, since, extraction_uid, offset, progress
                    )
                )
            except Exception:
                logger.exception("delta sync of %s interrupted", model)
                raise
            _apply_deletions(backend, model, since, store)
            DFStorage.touch_sync(model)
            DFStorage.clear_sync_state(model)
            continue

        if not last_sync:
            store.update(build_store(backend, extraction_uid, progress))
            continue
        since = last_sync
        DFStorage.set_sync_state(model, {"mode": "delta", "offset": 0, "since": since})
        try:
            store.update(
                _extract_delta_model(backend, model, since, extraction_uid, 0, progress)
            )
        except Exception:
            logger.exception("delta sync of %s interrupted", model)
            raise
        _apply_deletions(backend, model, since, store)
        DFStorage.touch_sync(model)
        DFStorage.clear_sync_state(model)
    return store


def _apply_deletions(backend: "Backend", model: str, since: str, store: dict):
    deleted_ids = backend.get_deletions(model, since)
    if deleted_ids:
        logger.info("sync %s : %s records deleted", model, len(deleted_ids))
        df = DFStorage.delete_records(model, deleted_ids)
        if df is not None:
            store[model] = df


def load_store() -> dict[str, pl.DataFrame]:
    """Load dataframes from the existing parquet files."""
    return {
        table: DFStorage.retrieve_df(table)["df"]
        for table in DFStorage.list_table_names()
    }


def user_store(backend: "Backend", user_id: int) -> dict[str, pl.DataFrame]:
    """Per-user view of the store (ACL columns + translatable lang)."""
    lang = backend.get_user_lang(user_id)
    store: dict[str, pl.DataFrame] = {}
    for table in DFStorage.list_table_names():
        try:
            allowed = backend.get_allowed_fields(table, user_id)
            row = DFStorage.retrieve_df(table, allowed_fields=allowed, lang=lang)
            if row:
                store[table] = row["df"]
        except Exception:
            logger.exception("user store fetch failed for %s", table)
    return store
