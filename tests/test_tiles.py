import datetime

import polars as pl
import pytest

from kpiten_core import serial, sandbox, tiles

DF = pl.DataFrame(
    {
        "id": [1, 2, 3, 4],
        "name": ["Alice", "Bob", "Alice", "Bob"],
        "amount_untaxed": [10.0, 20.0, 30.0, 40.0],
        "state": ["sale", "sale", "draft", "sale"],
        "date_order": [
            datetime.date(2025, 1, 1),
            datetime.date(2025, 2, 1),
            datetime.date(2025, 3, 1),
            datetime.date(2025, 4, 1),
        ],
    }
)

STORE = {"sale.order": DF}

NO_PREDICATES = []


def test_serial_roundtrip():
    d = {"x": {"name": "a"}, "y": {"name": "b", "aggregation": "sum"}}
    assert serial.loads(serial.dumps(d)) == d


def test_card():
    res = tiles.exec_tile(
        {
            "kind": "card",
            "name": "count",
            "content": "where = \"state = 'sale'\"",
        },
        "sale.order",
        STORE,
        NO_PREDICATES,
    )
    assert res.value == 3


def test_graph():
    content = serial.dumps(
        {
            "graph_type": "bar",
            "from": "sale.order",
            "x": {"name": "name", "aggregation": "none"},
            "y": {"name": "amount_untaxed", "aggregation": "sum"},
        }
    )
    res = tiles.exec_tile(
        {"kind": "graph", "name": "By vendor", "content": content},
        "sale.order",
        STORE,
        NO_PREDICATES,
    )
    totals = sorted((x, y) for x, y in zip(res.figure.data[0].x, res.figure.data[0].y))
    assert totals == [("Alice", 40.0), ("Bob", 60.0)]


def test_pivot_column():
    content = serial.dumps(
        {
            "index": "name",
            "column": "date_order",
            "measure": "amount_untaxed",
            "from": "sale.order",
        }
    )
    res = tiles.exec_tile(
        {"kind": "pivot", "name": "p", "content": content},
        "sale.order",
        STORE,
        NO_PREDICATES,
    )
    assert sorted(res.df.columns) == [
        "2025-01-01",
        "2025-02-01",
        "2025-03-01",
        "2025-04-01",
        "name",
    ]


def test_data_kind():
    content = (
        "d_next = d\n"
        'd_next = d_next.select([pl.col("amount_untaxed").sum().alias("total")])'
    )
    res = tiles.exec_tile(
        {"kind": "data", "name": "Amount", "content": content},
        "sale.order",
        STORE,
        NO_PREDICATES,
    )
    assert res.df["total"][0] == 100.0


def test_sandbox_forbidden():
    with pytest.raises(ValueError):
        sandbox.run("d_next = __import__('os').listdir()", DF, "d", "d_next")
    with pytest.raises(ValueError):
        sandbox.run("d_next = d.map_elements(lambda v: v)", DF, "d", "d_next")


def test_unknown_table_raises():
    with pytest.raises(tiles.TileError):
        tiles.exec_tile(
            {"kind": "graph", "name": "x", "content": 'graph_type = "bar"'},
            "nope.model",
            STORE,
            NO_PREDICATES,
        )
