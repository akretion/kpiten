"""Taking the rows of a panel out of the dashboard, for a marimo notebook."""

import ast
import datetime
import io
import json
import os
import time
import zipfile

import polars as pl
import pytest

from kpiten_core import env, explore

D = datetime.date


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "explore_dir", str(tmp_path / "explore"))
    monkeypatch.setattr(env, "data_path", str(tmp_path / "data"))
    return tmp_path


STORE = {
    "sale.order": pl.DataFrame(
        {
            "id": list(range(1, 9)),
            "user_id": ["Marie"] * 8,
            "date_order": [D(2025, m, 1) for m in range(1, 9)],
        }
    ).lazy(),
    "sale.order.line": pl.DataFrame(
        {"id": [1, 2, 3], "order_id_": [1, 5, 8], "qty": [1, 2, 3]}
    ).lazy(),
    "purchase.order": pl.DataFrame({"id": [1]}).lazy(),  # not read by the panel
}
LINES = [
    {"model": "sale.order", "kind": "card", "content": ""},
    {"model": "sale.order", "kind": "graph", "content": 'from = "sale.order.line"\n'},
]


def build(**kwargs):
    return explore.build_archive(
        STORE,
        LINES,
        kwargs.pop("predicates", []),
        user_id=8,
        db="big",
        panel="Sales",
        **kwargs,
    )


def test_the_archive_holds_the_tables_of_the_panel(folder):
    name, data = build(filters_text="Period 2025")
    assert name == "kpiten-explore-big-Sales.zip"
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(zf.namelist()) == [
        "README.txt",
        "explore.py",
        "manifest.json",
        "sale.order.line.parquet",
        "sale.order.parquet",
    ]  # not purchase.order : the panel does not read it
    manifest = json.loads(zf.read("manifest.json"))
    assert (manifest["user_id"], manifest["panel"], manifest["filters"]) == (
        8,
        "Sales",
        "Period 2025",
    )
    assert manifest["tables"]["sale.order"]["columns"]["date_order"] == "Date"


def test_the_panel_filters_narrow_the_rows(folder):
    _, data = build(predicates=[pl.col("date_order") >= D(2025, 6, 1)])
    zf = zipfile.ZipFile(io.BytesIO(data))
    orders = pl.read_parquet(io.BytesIO(zf.read("sale.order.parquet")))
    assert orders["id"].to_list() == [6, 7, 8]
    # a predicate on a column a table does not have is not applied to it
    assert pl.read_parquet(io.BytesIO(zf.read("sale.order.line.parquet"))).height == 3


def test_a_table_over_the_cap_is_cut_and_says_so(folder):
    _, data = build(max_rows=3)
    zf = zipfile.ZipFile(io.BytesIO(data))
    meta = json.loads(zf.read("manifest.json"))["tables"]["sale.order"]
    assert (meta["rows"], meta["total_rows"], meta["truncated"]) == (3, 8, True)
    assert pl.read_parquet(io.BytesIO(zf.read("sale.order.parquet"))).height == 3
    assert "Cut at" in zf.read("explore.py").decode()


def test_the_notebook_is_python_on_the_parquets(folder):
    _, data = build()
    source = zipfile.ZipFile(io.BytesIO(data)).read("explore.py").decode()
    ast.parse(source)  # valid Python
    assert 'pl.scan_parquet(here / "sale.order.parquet")' in source
    assert 'tables["sale.order"]' in source  # `d` starts on the tile's table


def test_nothing_is_left_behind_and_the_export_is_logged(folder):
    build()
    leftovers = list((folder / "explore").glob("explore-*"))
    assert leftovers == []
    entry = json.loads((folder / "explore.log").read_text().splitlines()[-1])
    assert (entry["user_id"], entry["panel"], entry["rows"]["sale.order"]) == (
        8,
        "Sales",
        8,
    )


def test_a_forgotten_export_is_purged(folder):
    stale = explore.export_dir() / "explore-stale"
    stale.mkdir()
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    build()
    assert not stale.exists()
