"""The demo tiles, and their drill-downs, on real samples : no Odoo, the real columns.

`tests/data` holds a sample of the rows of each demo model, as the KpiTen store has them
(parquet_sample), and the tiles of their datasets. `make sample-fixtures` regenerates them.
"""

import datetime
import json
import pathlib

import polars as pl
import pytest

from kpiten_core import filters, tiles

DATA = pathlib.Path(__file__).parent / "data"
MODELS = ["sale.order", "sale.order.line", "purchase.order", "purchase.order.line"]
TILES = (
    json.loads((DATA / "tiles.json").read_text())
    if (DATA / "tiles.json").exists()
    else []
)

pytestmark = pytest.mark.skipif(not TILES, reason="no fixtures : make sample-fixtures")


def tile_id(tile):
    return f"{tile['panel']}:{tile['name']}"


def line_of(tile):
    return {
        "kind": tile["kind"],
        "name": tile["name"],
        "content": tile["definition"],
        "drill": tile["drill"],
    }


@pytest.fixture(scope="module")
def store():
    return {m: pl.read_parquet(DATA / f"{m}.parquet").lazy() for m in MODELS}


@pytest.mark.parametrize("tile", TILES, ids=tile_id)
def test_every_tile_runs_on_the_sample(tile, store):
    result = tiles.exec_tile(line_of(tile), tile["model"], store, [])
    assert result.kind == tile["kind"]
    if result.df is not None:  # the hidden key columns never reach the table
        assert not [c for c in result.df.columns if c.startswith("__")]


@pytest.mark.parametrize("tile", [t for t in TILES if t["drill"]], ids=tile_id)
def test_the_drill_down_of_a_row_finds_rows(tile, store):
    result = tiles.exec_tile(line_of(tile), tile["model"], store, [])
    if not result.keys:
        pytest.skip(
            "the sample has no row for this table (no such data in the database)"
        )
    detail = tiles.exec_drill(line_of(tile), tile["model"], store, [], result.keys[0])
    assert detail.df.height >= 1  # the row of the table comes from these rows
    assert not [c for c in detail.df.columns if c.startswith("__")]


def test_the_cards_of_a_panel_compare_with_the_previous_period(store):
    """On the last half of the sample's dates : a card with `compare` has a comparison."""
    compared = 0
    for tile in TILES:
        config = tile["filter_config"]
        if tile["kind"] != "card" or not config.get("date"):
            continue
        low, high = filters.date_range(store, config)
        period = (low + (high - low) / 2, high)
        result = tiles.exec_tile(
            line_of(tile),
            tile["model"],
            store,
            filters.make_predicates(config, period, {}),
            filters.make_previous_predicates(config, period, {}),
            filters.describe_previous(period),
        )
        assert isinstance(result.value, (int, float, str, type(None), datetime.date))
        compared += result.comparison is not None
    assert compared >= 3  # the Sales and Purchase cards that ask for it
