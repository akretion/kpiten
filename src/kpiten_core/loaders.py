"""Framework-agnostic store loaders (extract / parquet / per-user views).

Shared by the dashboard apps (shiny, nicegui...): builds the parquet
snapshot from Odoo and returns per-user column-filtered dataframes.

`sync_store` refreshes the parquets incrementally : only records created or
written since the last sync are re-extracted (upsert), and deletions are
applied from the `auditlog` module (unlink logs).
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import polars as pl

from kpiten_core.dfnorm import Df
from kpiten_core.store import DFStorage

if TYPE_CHECKING:
    from kpiten_core.backend import Backend

logger = logging.getLogger(__name__)


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


def build_store(backend: "Backend", extraction_uid: int) -> dict[str, pl.DataFrame]:
    """Extract all declared datasets (kt.dataset) and refresh parquets."""
    models = backend.get_dataset_models()
    store: dict[str, pl.DataFrame] = {}
    for model in models:
        logger.info("extracting %s", model)
        raw_vals = backend.get_record_vals(model, [], extraction_uid)
        if not raw_vals:
            logger.warning("no records for %s", model)
            continue
        df = _extract_df(backend, model, raw_vals)
        store[model] = df
    return store


def _extract_df(backend: "Backend", model: str, raw_vals: list[dict]) -> pl.DataFrame:
    metadata = backend.get_fields_metadata(model)
    df = Df.from_raw(model, raw_vals, metadata).get_df()
    DFStorage.store_raw(model, raw_vals, metadata, df)
    return df


def sync_store(backend: "Backend", extraction_uid: int) -> dict[str, pl.DataFrame]:
    """Incremental refresh : full extract on first run, delta afterwards.

    Per table :
    - new / updated records (`create_date`/`write_date` > last_sync) are
      normalized and upserted in the parquet
    - deletions recorded by the `auditlog` module are applied
    """
    store: dict[str, pl.DataFrame] = {}
    for model in backend.get_dataset_models():
        last_sync = DFStorage.last_sync(model)
        if not last_sync:
            store.update(build_store(backend, extraction_uid))
            continue
        raw_vals = backend.get_updated_record_vals(model, last_sync, extraction_uid)
        if raw_vals:
            logger.info("sync %s : %s records upserted", model, len(raw_vals))
            df = DFStorage.append_records(model, raw_vals)
            store[model] = df
        deleted_ids = backend.get_deletions(model, last_sync)
        if deleted_ids:
            logger.info("sync %s : %s records deleted", model, len(deleted_ids))
            df = DFStorage.delete_records(model, deleted_ids)
            if df is not None:
                store[model] = df
        DFStorage.touch_sync(model)
    return store


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
