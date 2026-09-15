"""JSONL staging for the initial (recent->oldest) parquet load.

Odoo dumps raw records as JSONL on a shared volume (one file per paginated
chunk, `<offset>.jsonl`) through `Backend.write_staging_chunk`. The app never
needs the raw data over the wire : it only asks Odoo to write the chunk, then
reads the JSONL back from the shared volume.

This module owns that staging area on the app side :
- `next_offset`  : resume point, deduced from the chunks already present
  (no extra state to persist).
- `pull_batch`   : ask Odoo to write chunks until a record budget is reached.
- `consolidate`  : read every chunk, normalize (Df) and write the final
  parquet in a single pass (replacing the O(n^2) incremental parquet writes
  of the old initial load).

The staging dir is the same shared volume Odoo writes to (`kpiten_staging_dir`
system parameter), scoped per database like the final parquets.
"""

import logging
import pathlib
import shutil

import polars as pl

from kpiten_core.dfnorm import Df
from kpiten_core.store import DFStorage

logger = logging.getLogger(__name__)


class Stage:
    @classmethod
    def dir(cls, backend, table: str) -> pathlib.Path:
        """Staging dir for a table : <staging_dir>/<db>/<table>/."""
        return pathlib.Path(backend.get_staging_dir()) / backend.env.db / table

    @classmethod
    def next_offset(cls, backend, table: str) -> int:
        """Offset where a dump should resume, from the chunks already on disk.

        A chunk `<offset>.jsonl` holds a variable number of records, so the
        resume point is `offset + line_count` of the farthest chunk.
        """
        table_dir = cls.dir(backend, table)
        if not table_dir.exists():
            return 0
        furthest = 0
        for chunk in table_dir.glob("*.jsonl"):
            offset = int(chunk.stem)
            count = sum(1 for _ in chunk.open())
            furthest = max(furthest, offset + count)
        return furthest

    @classmethod
    def pull_batch(
        cls,
        backend,
        table: str,
        offset: int,
        domain: list,
        order: str,
        budget: int,
        page_size: int,
        extraction_uid: int,
        progress=None,
        mode: str = "initial",
    ):
        """Ask Odoo to dump chunks until `budget` records are staged.

        Returns (rows_pulled, done) ; done=True when Odoo returned fewer
        records than a full page (i.e. the table is fully staged).
        """
        rows = 0
        done = False
        while rows < budget:
            n = backend.write_staging_chunk(
                table, offset, page_size, domain, order, user_id=extraction_uid
            )
            if not n:
                done = True
                break
            rows += n
            offset += n
            if progress:
                progress(table, mode, offset, n, page_size)
            if n < page_size:
                done = True
                break
        return rows, done

    @classmethod
    def consolidate(cls, backend, table: str, metadata: dict):
        """Read all staged chunks, normalize and write the final parquet once.

        The JSONL chunks are the raw values straight from Odoo (same shape as
        the jsonrpc path), so `Df` normalizes them identically and the result
        is schema-equivalent to the previous extraction. Staging files are
        removed once consumed.
        """
        table_dir = cls.dir(backend, table)
        chunks = sorted(table_dir.glob("*.jsonl")) if table_dir.exists() else []
        if not chunks:
            logger.warning("consolidate %s : no staged chunks", table)
            return
        logger.info("consolidating %s from %s chunks", table, len(chunks))
        df = pl.read_ndjson(chunks, infer_schema_length=None)
        norm = Df(df, fields=metadata).get_df()
        DFStorage.store_raw(table, [], metadata, norm)
        shutil.rmtree(table_dir, ignore_errors=True)
