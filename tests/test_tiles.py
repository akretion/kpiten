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
    assert res.text == "3"


PURCHASES = pl.DataFrame(
    {
        "id": [1, 2, 3, 4],
        "state": ["purchase", "purchase", "draft", "done"],
        "amount_untaxed": [100.0, 300.0, 50.0, 200.0],
        "create_date": [datetime.date(2025, 1, 1)] * 4,
        "date_approve": [
            datetime.date(2025, 1, 3),
            datetime.date(2025, 1, 5),
            None,
            datetime.date(2025, 1, 2),
        ],
        "date_planned": [datetime.date(2025, 1, 10)] * 4,
    }
)


def card(definition: dict, store=None) -> tiles.TileResult:
    return tiles.exec_tile(
        {"kind": "card", "name": "card", "content": serial.dumps(definition)},
        "purchase.order",
        store or {"purchase.order": PURCHASES},
        NO_PREDICATES,
    )


def test_card_sum_with_unit():
    res = card(
        {
            "where": "state in ('purchase', 'done')",
            "aggregation": "sum",
            "measure": "amount_untaxed",
            "unit": "€",
        }
    )
    assert res.value == 600.0
    assert res.text == "600 €"


def test_card_mean_derived_days():
    res = card(
        {
            "aggregation": "mean",
            "measure": "days_to_order",
            "unit": "days",
            "derive": {"days_to_order": "date_approve - create_date"},
        }
    )
    assert res.value == pytest.approx(7 / 3)  # null (draft) is ignored
    assert res.text == "2.3 days"


def test_card_where_on_derived_column():
    res = card(
        {
            "where": "days_to_order > 1",  # delays are 2, 4, null, 1
            "derive": {"days_to_order": "date_approve - create_date"},
        }
    )
    assert res.value == 2


def test_card_today_placeholders(monkeypatch):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2025, 1, 12)

    monkeypatch.setattr(tiles.datetime, "date", FrozenDate)
    late = card({"where": "date_planned < '{today}'"})
    assert late.value == 4
    recent = card({"where": "date_planned >= '{today-2}'"})  # >= 2025-01-10
    assert recent.value == 4
    not_yet = card({"where": "date_planned > '{today}'"})
    assert not_yet.value == 0


def test_card_empty_selection():
    assert card({"where": "state = 'nope'", "aggregation": "count"}).text == "0"
    empty_mean = card(
        {"where": "state = 'nope'", "aggregation": "mean", "measure": "amount_untaxed"}
    )
    assert empty_mean.value is None
    assert empty_mean.text == "–"


def test_card_thousands_and_decimals():
    big = pl.DataFrame({"id": [1], "amount_untaxed": [1234567.891]})
    res = card(
        {"aggregation": "sum", "measure": "amount_untaxed", "decimals": 2},
        store={"purchase.order": big},
    )
    assert res.text == "1 234 567.89"


def test_card_ignore_period_keeps_dimension_filters():
    """The Period filter (a date predicate) is dropped, a vendor filter stays."""
    df = PURCHASES.with_columns(
        pl.Series("vendor", ["A", "A", "B", "B"]),
        pl.Series("date_order", [datetime.date(2025, 1, d) for d in (1, 5, 9, 20)]),
    )
    predicates = [
        pl.col("date_order") <= datetime.date(2025, 1, 10),  # Period filter
        pl.col("vendor").is_in(["B"]),  # dimension filter
    ]

    def run(definition):
        line = {"kind": "card", "name": "c", "content": serial.dumps(definition)}
        return tiles.exec_tile(line, "p", {"p": df}, predicates).value

    assert run({}) == 1  # period AND vendor : B on 2025-01-09
    assert run({"ignore_period": True}) == 2  # vendor only : B twice
    assert run({"ignore_period": False}) == 1


def test_card_errors():
    with pytest.raises(tiles.TileError, match="needs a `measure`"):
        card({"aggregation": "sum"})
    with pytest.raises(tiles.TileError, match="unknown card aggregation"):
        card({"aggregation": "variance", "measure": "amount_untaxed"})
    with pytest.raises(tiles.TileError, match="unknown column"):
        card({"derive": {"x": "nope - create_date"}})


def test_validate_card():
    from kpiten_core import validate_toml

    ok = 'aggregation = "mean"\nmeasure = "days"\n[derive]\ndays = "b - a"\n'
    assert validate_toml(ok, "card") == []
    assert validate_toml('where = "state = 1"', "card") == []
    bad = validate_toml('aggregation = "sum"\nunit = 3\nfoo = 1', "card")
    assert "Unknown key 'foo' in card" in bad
    assert "Key 'unit' in card must be str" in bad
    assert "Aggregation 'sum' in card needs a 'measure'" in bad
    assert validate_toml('[derive]\nx = "a + b"', "card") == [
        "Derived column 'x' must be '<date> - <date>'"
    ]


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


def test_lazy_store_gives_the_same_tiles():
    """A store of LazyFrames (what user_store serves) computes the same tiles
    as one of DataFrames, without loading the table."""
    lazy = {name: df.lazy() for name, df in STORE.items()}
    cases = [
        ("card", {"aggregation": "sum", "measure": "amount_untaxed"}),
        (
            "graph",
            {
                "graph_type": "bar",
                "x": {"name": "name", "aggregation": "none"},
                "y": {"name": "amount_untaxed", "aggregation": "sum"},
            },
        ),
        (
            "pivot",
            {
                "index": "name",
                "column": "date_order",
                "measure": "amount_untaxed",
                "aggregation": "mean",
            },
        ),
        ("data", "d_next = d \nd_next = d_next.sort('name')\n"),
        # eager-only method : the snippet falls back on the loaded rows
        (
            "data",
            "d_next = d \nd_next = d_next.select(['name', 'amount_untaxed']).transpose()\n",
        ),
    ]
    for kind, definition in cases:
        content = (
            definition if isinstance(definition, str) else serial.dumps(definition)
        )
        line = {"kind": kind, "name": kind, "content": content}
        eager = tiles.exec_tile(line, "sale.order", STORE, NO_PREDICATES)
        got = tiles.exec_tile(line, "sale.order", lazy, NO_PREDICATES)
        assert got.value == eager.value
        if kind in ("pivot", "data"):
            assert got.df.equals(eager.df), kind
        if kind == "graph":
            assert got.figure.to_json() == eager.figure.to_json()


def test_graph_where_and_monthly():
    """`where` keeps the confirmed orders, `monthly` gives one point per month,
    in chronological order."""
    df = pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "state": ["sale", "sale", "draft", "sale", "cancel"],
            "amount_untaxed": [10.0, 20.0, 999.0, 40.0, 999.0],
            "date_order": [
                datetime.date(2025, 3, 5),
                datetime.date(2025, 3, 20),
                datetime.date(2025, 3, 21),
                datetime.date(2025, 1, 2),
                datetime.date(2025, 2, 2),
            ],
        }
    )
    content = serial.dumps(
        {
            "graph_type": "area",
            "where": "state not in ('draft', 'cancel', 'sent')",
            "monthly": True,
            "x": {"name": "date_order", "aggregation": "none"},
            "y": {"name": "amount_untaxed", "aggregation": "sum"},
        }
    )
    res = tiles.exec_tile(
        {"kind": "graph", "name": "Monthly sales", "content": content},
        "sale.order",
        {"sale.order": df},
        NO_PREDICATES,
    )
    trace = res.figure.data[0]
    assert list(trace.x) == [datetime.date(2025, 1, 1), datetime.date(2025, 3, 1)]
    assert list(trace.y) == [40.0, 30.0]
    from kpiten_core import validate_toml

    assert validate_toml(content, "graph", set(df.columns)) == []
