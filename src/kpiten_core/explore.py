"""Take the rows of a panel out of the dashboard, to explore them in a marimo notebook.

The rows come from the user's store : his columns and his rows only (the Odoo rules were
applied when the store was built), narrowed by the panel filters he has set. Nothing reaches
the notebook that the dashboard would not show him, and the notebook has no Odoo nor
Postgres credential : it is a zip of parquets, run by the user on his own machine.

`build_archive` is the entry point : one parquet per table, `manifest.json` (who, when, which
filters, which columns), a starter notebook `explore.py` and a README. Each export is logged
(`explore.log`), the temporary files are removed at once and anything left is purged.
"""

import datetime
import json
import logging
import pathlib
import shutil
import tempfile
import time
import zipfile

import polars as pl

from kpiten_core import env, serial
from kpiten_core.tiles import filter_df

logger = logging.getLogger(__name__)


def export_dir() -> pathlib.Path:
    """Where exports are built : private to the process user, never under the parquets."""
    path = pathlib.Path(
        env.explore_dir or pathlib.Path(env.data_path).parent / "explore"
    )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def purge(older_than_hours: int | None = None) -> None:
    """Remove the export directories that were left behind (a crash, a killed worker)."""
    limit = time.time() - 3600 * (older_than_hours or env.explore_ttl_hours)
    for child in export_dir().iterdir():
        if child.is_dir() and child.stat().st_mtime < limit:
            shutil.rmtree(child, ignore_errors=True)


def panel_tables(lines: list[dict], store: dict) -> list[str]:
    """The tables of the store the tiles of a panel read : their datasets, and the tables
    a graph, a pivot or a union takes (`from`, `union_model`, `mapping`)."""
    names = []
    for line in lines:
        wanted = [line.get("model")]
        if line.get("kind") not in ("data", "card") or "from" in (
            line.get("content") or ""
        ):
            try:
                definition = serial.loads(line.get("content") or "")
            except Exception:
                definition = {}
            wanted += [definition.get("from"), definition.get("union_model")]
            wanted += list(definition.get("mapping") or {})
        names += [n for n in wanted if n and n in store and n not in names]
    return names


def write_tables(store, names, predicates, folder, max_rows) -> dict:
    """One parquet per table : the rows the panel filters keep, cut at `max_rows`."""
    tables = {}
    for name in names:
        lazy = filter_df(store[name].lazy(), predicates)
        total = lazy.select(pl.len()).collect().item()
        path = folder / f"{name}.parquet"
        lazy.head(max_rows).collect().write_parquet(path)
        tables[name] = {
            "file": path.name,
            "rows": min(total, max_rows),
            "total_rows": total,
            "truncated": total > max_rows,
            "columns": {c: str(t) for c, t in lazy.collect_schema().items()},
        }
    return tables


NOTEBOOK = '''import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import pathlib

    import marimo as mo
    import polars as pl

    here = pathlib.Path(__file__).parent
    return here, mo, pl


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # KpiTen : {panel}

    The rows of the dashboard with the rights of **user {user_id}**, taken {created}.
    Filters : {filters}
{warning}    """)
    return


@app.cell
def _(here, pl):
    # one lazy table per parquet : the same tables as the dashboard's tiles
    tables = {{
{tables}
    }}
    return (tables,)


@app.cell
def _(mo, tables):
    mo.ui.table(
        [
            {{"table": name, "columns": len(lazy.collect_schema())}}
            for name, lazy in tables.items()
        ]
    )
    return


@app.cell
def _(tables):
    # Same idea as a KpiTen "Data" tile : `d` is a table, `d_next` the result
    d = tables["{main}"]
    d_next = d.head(20)
    d_next.collect()
    return d, d_next


if __name__ == "__main__":
    app.run()
'''

README = """KpiTen explore
==============

{count} table(s) of the panel "{panel}", with the rights of user {user_id}, taken {created}.
{filters}

- `manifest.json` : the tables, their rows and columns, the filters.
- `explore.py` : a marimo notebook on these files -- `pip install marimo polars`, then
  `marimo edit explore.py`.

These are data you may see in the dashboard : keep them as you would keep the dashboard.
"""


def notebook(manifest: dict, main: str) -> str:
    tables = "\n".join(
        f'        "{name}": pl.scan_parquet(here / "{meta["file"]}"),'
        for name, meta in manifest["tables"].items()
    )
    cut = [n for n, m in manifest["tables"].items() if m["truncated"]]
    warning = (
        f"\n    **Cut at {env.explore_max_rows} rows :** {', '.join(cut)}.\n"
        if cut
        else ""
    )
    return NOTEBOOK.format(
        panel=manifest["panel"],
        user_id=manifest["user_id"],
        created=manifest["created"],
        filters=manifest["filters"] or "none",
        warning=warning,
        tables=tables,
        main=main,
    )


def build_archive(
    store: dict,
    lines: list[dict],
    predicates: list,
    *,
    user_id: int,
    db: str,
    panel: str,
    filters_text: str = "",
    max_rows: int | None = None,
) -> tuple[str, bytes]:
    """The zip to download : `(filename, bytes)`. `store` is the store of THE USER."""
    max_rows = max_rows or env.explore_max_rows
    names = panel_tables(lines, store) or list(store)
    created = datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    purge()
    folder = pathlib.Path(tempfile.mkdtemp(prefix="explore-", dir=export_dir()))
    try:
        manifest = {
            "db": db,
            "panel": panel,
            "user_id": user_id,
            "created": created,
            "filters": filters_text,
            "tables": write_tables(store, names, predicates, folder, max_rows),
        }
        main = (lines[0].get("model") if lines else None) or names[0]
        if main not in manifest["tables"]:
            main = next(iter(manifest["tables"]))
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=1))
        (folder / "explore.py").write_text(notebook(manifest, main))
        (folder / "README.txt").write_text(
            README.format(
                count=len(names),
                panel=panel,
                user_id=user_id,
                created=created,
                filters=f"Filters : {filters_text}" if filters_text else "",
            )
        )
        archive = folder / "archive.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(folder.iterdir()):
                if path != archive:
                    zf.write(path, path.name)
        data = archive.read_bytes()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    with (export_dir().parent / "explore.log").open("a") as log:
        log.write(
            json.dumps(
                {
                    "at": created,
                    "db": db,
                    "user_id": user_id,
                    "panel": panel,
                    "filters": filters_text,
                    "rows": {n: m["rows"] for n, m in manifest["tables"].items()},
                    "bytes": len(data),
                }
            )
            + "\n"
        )
    logger.info("explore : user %s, panel %s, %s bytes", user_id, panel, len(data))
    return f"kpiten-explore-{db}-{panel}.zip".replace(" ", "_"), data
