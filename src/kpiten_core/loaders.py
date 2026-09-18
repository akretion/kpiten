"""Framework-agnostic store loaders (extract / parquet / per-user views).

Shared by the dashboard apps (shiny, nicegui...): builds the parquet
snapshot from Odoo and returns per-user column-filtered dataframes.

Extraction always streams straight from Postgres with connectorx
(`EXTRACT_MODE = sql | view`), bypassing the Odoo ORM/RPC entirely for the
bulk data. `sync_store` refreshes the parquets incrementally : only records
created or written since the last sync are re-extracted (upsert), and
deletions are applied from the `auditlog` module (unlink logs).
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

import polars as pl

from kpiten_core import env, resolve
from kpiten_core.dfnorm import Df
from kpiten_core.store import DFStorage

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


def _pull_sql(
    backend: "Backend",
    base_query: str,
    metadata: dict,
    model: str,
    mode: str,
    progress: ProgressFn | None,
) -> "pl.DataFrame | None":
    """Pull `base_query` by bounded connectorx pages, then resolve+normalize once.

    Pages are kept as raw (bare-int m2o columns) and only concatenated once
    the whole result is in : resolving display names and normalizing on the
    full frame means one batched RPC call per m2o field (however many pages
    it took) instead of one per page, which matters for a field with high
    cardinality (e.g. order_id on sale.order.line) where nearly every page
    would otherwise hit new, unresolved ids.
    """
    uri = _pg_uri(backend.env.db)
    pages = []
    total = 0
    for page in _iter_sql_pages(uri, base_query, env.sync_page_size):
        pages.append(page)
        total += page.height
        if progress:
            progress(model, mode, total, page.height, env.sync_page_size)
    if not pages:
        return None
    raw = pl.concat(pages, how="vertical_relaxed")
    raw = resolve.inject_display_names(backend, raw, metadata)
    return Df(raw, fields=metadata).get_df()


def _extract_full_model(
    backend: "Backend",
    model: str,
    extraction_uid: int,
    progress: ProgressFn | None = None,
):
    """Full extract of one model straight from Postgres, paged by id.

    Each page is one bounded connectorx query (`env.sync_page_size` rows), so
    a single call never has to hold an arbitrarily large result in memory the
    way one unbounded query over the whole table would.
    """
    logger.info("extracting %s via direct SQL", model)
    metadata = backend.get_fields_metadata(model)
    if env.extract_mode == "view":
        base_query = f"SELECT * FROM {backend.get_view_name(model)}"
    else:
        base_query = backend.get_sql_query(model, [], "")
    norm = _pull_sql(backend, base_query, metadata, model, "full", progress)
    if norm is None:
        logger.warning("no records for %s", model)
        return {}
    DFStorage.store_raw(model, [], metadata, norm)
    return {model: norm}


def _extract_delta_model(
    backend: "Backend",
    model: str,
    since: str,
    progress: ProgressFn | None = None,
) -> pl.DataFrame | None:
    """Delta extract of one model straight from Postgres (write/create > since).

    Same bounded per-page connectorx pagination as the full extract ; the
    result is upserted into the existing parquet in a single write
    (`DFStorage.merge_df`). Returns None when nothing changed.
    """
    logger.info("delta-syncing %s via direct SQL (since=%s)", model, since)
    metadata = backend.get_fields_metadata(model)
    domain = ["|", ("write_date", ">", since), ("create_date", ">", since)]
    base_query = backend.get_sql_query(model, domain, "")
    new_df = _pull_sql(backend, base_query, metadata, model, "delta", progress)
    if new_df is None:
        return None
    return DFStorage.merge_df(model, new_df)


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


def _apply_deletions(uri: str, model: str, since: str, store: dict):
    deleted_ids = _get_deletions(uri, model, since)
    if deleted_ids:
        logger.info("sync %s : %s records deleted", model, len(deleted_ids))
        df = DFStorage.delete_records(model, deleted_ids)
        if df is not None:
            store[model] = df


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
) -> dict[str, pl.DataFrame]:
    """Full extract of every declared dataset (kt.dataset), via connectorx."""
    store: dict[str, pl.DataFrame] = {}
    for model in backend.get_dataset_models():
        store.update(_extract_full_model(backend, model, extraction_uid, progress))
    return store


def sync_store(
    backend: "Backend", extraction_uid: int, progress: ProgressFn | None = None
) -> dict[str, pl.DataFrame]:
    """Incremental refresh : full extract on first run, delta afterwards.

    Per table :
    - new / updated records (`create_date`/`write_date` > last_sync) are
      normalized and upserted in the parquet
    - deletions recorded by the `auditlog` module are applied
    """
    store: dict[str, pl.DataFrame] = {}
    uri = _pg_uri(backend.env.db)
    for model in backend.get_dataset_models():
        since = DFStorage.last_sync(model)
        if not since:
            store.update(_extract_full_model(backend, model, extraction_uid, progress))
            continue
        df = _extract_delta_model(backend, model, since, progress)
        if df is not None:
            store[model] = df
        _apply_deletions(uri, model, since, store)
        DFStorage.touch_sync(model)
    return store


def load_store() -> dict[str, pl.DataFrame]:
    """Load dataframes from the existing parquet files."""
    return {
        table: DFStorage.retrieve_df(table)["df"]
        for table in DFStorage.list_table_names()
    }


def accessible_ids(backend: "Backend", table: str, user_id: int) -> pl.Series:
    """Ids of the `table` records the user may read.

    Odoo builds the `SELECT id` with its own record rules (ir.rule) applied for
    that user ; it is run here straight against Postgres, like the extraction.
    """
    query = backend.get_access_query(table, user_id)
    if not query:  # no read access to the model at all
        return pl.Series("id", [], dtype=pl.Int64)
    return _read_sql_df(_pg_uri(backend.env.db), query)["id"]


def restrict_rows(df: pl.DataFrame, ids: pl.Series) -> pl.DataFrame:
    """The rows of `df` whose `id` is in `ids`."""
    return df.filter(pl.col("id").is_in(ids.implode()))


def user_store(backend: "Backend", user_id: int) -> dict[str, pl.DataFrame]:
    """Per-user view of the store : the columns the user may read (ACL), the
    rows the user may read (record rules), translatable lang.

    A table whose access could not be resolved is left out : the user sees
    nothing of it rather than everything.
    """
    lang = backend.get_user_lang(user_id)
    store: dict[str, pl.DataFrame] = {}
    with env.db_scope(backend.env.db):
        for table in DFStorage.list_table_names():
            try:
                allowed = backend.get_allowed_fields(table, user_id)
                row = DFStorage.retrieve_df(table, allowed_fields=allowed, lang=lang)
                if row:
                    ids = accessible_ids(backend, table, user_id)
                    store[table] = restrict_rows(row["df"], ids)
            except Exception:
                logger.exception("user store fetch failed for %s", table)
    return store
