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

from kpiten_core import env
from kpiten_core.dfnorm import Df
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
    offset: int = 0,
    progress: ProgressFn | None = None,
):
    """Paginated full extract of one model, resuming at `offset`.

    Each bounded chunk is committed to the parquet as soon as it is fetched
    (first chunk overwrites, following ones upsert), so an interruption only
    loses the in-flight chunk and the saved offset lets the next call resume.
    """
    logger.info("extracting %s (offset=%s)", model, offset)
    store: dict[str, pl.DataFrame] = {}
    metadata = backend.get_fields_metadata(model)
    # resume (offset > 0) : the parquet already holds earlier chunks, append ;
    # fresh start (offset == 0) : the first chunk overwrites the table
    first = offset == 0
    for chunk in _iter_chunks(
        backend,
        model,
        [],
        extraction_uid,
        offset=offset,
        progress=progress,
        mode="full",
    ):
        if first:
            df = Df.from_raw(model, chunk, metadata).get_df()
            DFStorage.store_raw(model, chunk, metadata, df)
            first = False
        else:
            df = DFStorage.append_records(model, chunk)
        store[model] = df
        offset += len(chunk)
        # persist progress so an interruption resumes at the last committed chunk
        DFStorage.set_sync_state(model, {"mode": "full", "offset": offset})
    if first:
        logger.warning("no records for %s", model)
    return store


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
        state = DFStorage.get_sync_state(model)
        offset = state["offset"] if state and state.get("mode") == "full" else 0
        if offset:
            logger.info("resuming full extract of %s at offset=%s", model, offset)
        DFStorage.set_sync_state(model, {"mode": "full", "offset": offset})
        try:
            store.update(
                _extract_full_model(backend, model, extraction_uid, offset, progress)
            )
        except Exception:
            # keep the state so the next sync resumes where we stopped
            logger.exception("full extract of %s interrupted", model)
            raise
        DFStorage.clear_sync_state(model)
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


def _pull_model_batch(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    offset: int,
    max_date: str,
    budget: int,
    progress: ProgressFn | None = None,
):
    """Pull up to `budget` records of `model`, most recent create_date first.

    Each chunk is committed to the parquet as soon as it is fetched (first
    chunk initializes the table, following ones upsert), so an interruption
    only loses the in-flight chunk.

    Returns (rows_pulled, done) ; done=True when every record up to `max_date`
    has been pulled.
    """
    page = env.sync_page_size
    domain = [("create_date", "<=", max_date)]
    order = "create_date desc, id desc"
    metadata = None if offset else backend.get_fields_metadata(model)
    rows = 0
    done = False
    while rows < budget:
        raw_vals = backend.get_record_vals(
            model, domain, extraction_uid, limit=page, offset=offset, order=order
        )
        if not raw_vals:
            done = True
            break
        if offset == 0:
            df = Df.from_raw(model, raw_vals, metadata).get_df()
            DFStorage.init_table(model, raw_vals, metadata, df)
        else:
            df = DFStorage.append_records(model, raw_vals)
        rows += len(raw_vals)
        offset += len(raw_vals)
        if progress:
            progress(model, "initial", offset, len(raw_vals), page)
        if len(raw_vals) < page:
            done = True
            break
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
    """
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
    offset = current.get("offset", 0)
    rows, done = _pull_model_batch(
        backend, model, extraction_uid, offset, max_date, env.sync_batch_size, progress
    )
    if done:
        # table fully loaded : mark last_sync so delta syncs take over
        if DFStorage.table_exists(model):
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
            # resume an interrupted extraction, whatever its mode
            mode, offset = state["mode"], state["offset"]
            if mode == "full":
                DFStorage.set_sync_state(model, {"mode": "full", "offset": offset})
                try:
                    store.update(
                        _extract_full_model(
                            backend, model, extraction_uid, offset, progress
                        )
                    )
                except Exception:
                    logger.exception("full extract of %s interrupted", model)
                    raise
                DFStorage.clear_sync_state(model)
                continue
            # delta resume
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
