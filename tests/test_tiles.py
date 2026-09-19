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
    assert res.text == "2,3 days"


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
    assert res.text == "1\u202f234\u202f567,89"


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


def test_sandbox_does_not_read_files_through_sql(tmp_path):
    """Polars SQL reads files (`FROM read_parquet(...)`) : a snippet could read the
    parquets of every user, whatever the rights of the one who runs it."""
    secret = tmp_path / "secret.parquet"
    pl.DataFrame({"x": [1]}).write_parquet(secret)
    code = f"d_next = d.sql(\"SELECT * FROM read_parquet('{secret}')\")"
    with pytest.raises(ValueError, match="forbidden call: sql"):
        sandbox.run(code, DF, "d", "d_next")


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


def _graph_figure(graph_type):
    content = serial.dumps(
        {
            "graph_type": graph_type,
            "from": "sale.order",
            "x": {"name": "name", "aggregation": "none"},
            "y": {"name": "amount_untaxed", "aggregation": "sum"},
        }
    )
    return tiles.exec_tile(
        {"kind": "graph", "name": "G", "content": content},
        "sale.order",
        STORE,
        NO_PREDICATES,
    ).figure


def test_filled_graph_takes_the_configured_fill_color():
    """`graph.fill_color` of kt.config : the line of an area and its fill, at half
    opacity. Bars keep the palette, without a color plotly's default stays."""
    try:
        tiles.set_chart_config({"graph": {"fill_color": "#33d17a"}})
        area = _graph_figure("area").data[0]
        assert area.line.color == "#33d17a"
        assert area.fillcolor == "rgba(51, 209, 122, 0.5)"
        assert _graph_figure("bar").data[0].marker.color != "#33d17a"  # not a bar's

        tiles.set_chart_config({"graph": {"fill_color": "#abc"}})  # short hex
        assert _graph_figure("area").data[0].fillcolor == "rgba(170, 187, 204, 0.5)"

        tiles.set_chart_config({"graph": {"fill_color": "teal"}})  # a name : as it is
        assert _graph_figure("area").data[0].fillcolor == "teal"

        tiles.set_chart_config({})
        assert _graph_figure("area").data[0].line.color == "#636efa"  # plotly's
    finally:
        tiles.set_chart_config({})


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


def test_period_on_a_table_that_names_the_date_differently():
    """One Period filter, two date columns : each table keeps the predicate of
    the column it has (orders : date_order, their lines : order_id.date_order)."""
    from kpiten_core import filters

    config = {"date": {"field": ["date_order", "order_id.date_order"]}}
    period = (datetime.date(2025, 2, 1), datetime.date(2025, 3, 31))
    predicates = filters.make_predicates(config, period, {})
    assert len(predicates) == 4
    assert "date_order, order_id.date_order" in filters.describe_filters(
        config, period, {}
    )
    # a single name keeps working
    assert (
        len(filters.make_predicates({"date": {"field": "date_order"}}, period, {})) == 2
    )

    lines = pl.DataFrame(
        {
            "id": [1, 2, 3],
            "order_id.date_order": [
                datetime.date(2025, 1, 5),
                datetime.date(2025, 2, 5),
                datetime.date(2025, 3, 5),
            ],
        }
    )
    assert tiles.filter_df(lines, predicates)["id"].to_list() == [2, 3]
    assert tiles.filter_df(DF, predicates)["id"].to_list() == [2, 3]


def test_card_compares_with_the_previous_period():
    """`compare = true` : the card against the period right before, as a
    percentage of the previous value, like an Odoo scorecard."""
    from kpiten_core import filters

    config = {"date": {"field": "date_order"}}
    df = pl.DataFrame(
        {
            "id": range(1, 8),
            "state": ["sale"] * 7,
            "amount_untaxed": [10.0] * 3 + [10.0] * 4,
            "date_order": [datetime.date(2025, 1, d) for d in (2, 3, 4)]
            + [datetime.date(2025, 1, d) for d in (12, 13, 14, 15)],
        }
    )
    period = (datetime.date(2025, 1, 11), datetime.date(2025, 1, 20))
    assert filters.previous_bounds(period) == (
        datetime.date(2025, 1, 1),
        datetime.date(2025, 1, 10),
    )
    assert filters.describe_previous(period) == "2025-01-01 → 2025-01-10"
    line = {
        "kind": "card",
        "name": "Orders",
        "content": "where = \"state = 'sale'\"\ncompare = true\n",
    }
    res = tiles.exec_tile(
        line,
        "sale.order",
        {"sale.order": df},
        filters.make_predicates(config, period, {}),
        filters.make_previous_predicates(config, period, {}),
        filters.describe_previous(period),
    )
    assert res.value == 4  # 4 orders in the period, 3 before
    cmp = res.comparison
    assert (cmp["direction"], cmp["text"], cmp["previous"]) == ("up", "33.3%", "3")
    assert cmp["period"] == "2025-01-01 → 2025-01-10"

    # nothing to compare : no `compare`, no period, `ignore_period`
    plain = {**line, "content": "where = \"state = 'sale'\"\n"}
    args = ({"sale.order": df}, filters.make_predicates(config, period, {}))
    assert (
        tiles.exec_tile(
            plain,
            "sale.order",
            *args,
            filters.make_previous_predicates(config, period, {}),
        ).comparison
        is None
    )
    assert tiles.exec_tile(line, "sale.order", *args, None).comparison is None
    assert filters.make_previous_predicates(config, None, {}) is None
    ignored = {**line, "content": line["content"] + "ignore_period = true\n"}
    assert (
        tiles.exec_tile(
            ignored,
            "sale.order",
            *args,
            filters.make_previous_predicates(config, period, {}),
        ).comparison
        is None
    )

    # a fall, an unchanged value, a previous period without any row
    def compare(now, before):
        rows = pl.DataFrame({"tag": ["before"] * before})
        return tiles.card_comparison(
            "compare = true\n", "t", {"t": rows}, now, [pl.col("tag") == "before"]
        )

    fall = compare(5, 10)
    assert (fall["direction"], fall["text"], fall["previous"]) == (
        "down",
        "50.0%",
        "10",
    )
    same = compare(10, 10)
    assert (same["direction"], same["text"]) == ("neutral", "0.0%")
    new = compare(3, 0)
    assert (new["direction"], new["text"]) == ("up", "n/a")

    # the `kt.config` switch : off, no card compares ; nothing said, they do
    try:
        tiles.set_chart_config({"card": {"comparison": False}})
        assert compare(5, 10) is None
        tiles.set_chart_config({})
        assert compare(5, 10) is not None
    finally:
        tiles.set_chart_config({})


def test_best_card_shows_the_name_of_the_best_group():
    """`best` : the name with the biggest revenue, the units sold under it (the
    Best Seller / Best Category scorecards of Odoo's Product dashboard)."""
    from kpiten_core import validate_toml

    lines = pl.DataFrame(
        {
            "state": ["sale", "sale", "sale", "draft", "sale"],
            "product_id": ["Chair", "Desk", "Chair", "Sofa", None],
            "price_subtotal": [10.0, 100.0, 60.0, 9999.0, 5000.0],
            "product_uom_qty": [2.0, 1.0, 3.0, 50.0, 7.0],
        }
    )
    content = (
        'where = "state = \'sale\'"\nbest = "product_id"\n'
        'measure = "price_subtotal"\ndetail = "product_uom_qty"\ndetail_label = "sold"\n'
    )
    res = tiles.exec_tile(
        {"kind": "card", "name": "Best Seller", "content": content},
        "sale.order.line",
        {"sale.order.line": lines},
        [],
    )
    # Desk 100 > Chair 70 ; the draft Sofa and the line without product do not count
    assert (res.value, res.text, res.subtitle) == ("Desk", "Desk", "1 sold")
    assert res.comparison is None
    # nothing matches : a dash, no subtitle
    empty = tiles.exec_tile(
        {"kind": "card", "name": "x", "content": content.replace("'sale'", "'none'")},
        "sale.order.line",
        {"sale.order.line": lines},
        [],
    )
    assert (empty.value, empty.text, empty.subtitle) == (None, "–", None)
    assert validate_toml(content, "card", set(lines.columns)) == []
    assert validate_toml('best = "product_id"\n', "card") == [
        "Card 'best' needs a 'measure' to rank the groups"
    ]


def test_graph_keeps_the_biggest_bars_and_folds_the_rest_only_on_request(monkeypatch):
    from kpiten_core import env, validate_toml

    monkeypatch.setattr(env, "tile_max_categories", 3)
    df = pl.DataFrame(
        {"name": list("abcdef"), "amount_untaxed": [60.0, 50.0, 40.0, 30.0, 20.0, 10.0]}
    )

    def bars(extra):
        content = serial.dumps(
            {
                "graph_type": "bar",
                "x": {"name": "name", "aggregation": "none"},
                "y": {"name": "amount_untaxed", "aggregation": "sum"},
                **extra,
            }
        )
        assert validate_toml(content, "graph") == []
        res = tiles.exec_tile(
            {"kind": "graph", "name": "g", "content": content},
            "sale.order",
            {"sale.order": df},
            NO_PREDICATES,
        )
        trace = res.figure.data[0]
        return dict(zip(trace.x, trace.y)), res.note

    # a ranking : the three biggest, nothing that flattens them
    assert bars({}) == ({"a": 60.0, "b": 50.0, "c": 40.0}, "Top 3 of 6")
    folded, note = bars({"others": True})
    assert folded == {"a": 60.0, "b": 50.0, "c": 40.0, "Others": 60.0}
    assert note == "Top 3 of 6 (rest in Others)"
