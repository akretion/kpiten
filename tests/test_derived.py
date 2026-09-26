import polars as pl

from kpiten_core import derived

STORE = {
    "sale.order": pl.LazyFrame(
        {"id": [1, 2, 3], "state": ["sale", "draft", "sale"], "amount": [10.0, 20, 30]}
    )
}


def test_the_derived_tables_are_computed_on_the_store_in_order():
    definitions = [
        {"name": "total", "sql": "SELECT SUM(amount) AS t FROM confirmed", "mine": 1},
        # a shared table, and the user's own of the same name : the own one wins
        {"name": "confirmed", "sql": "SELECT * FROM d", "source": "sale.order"},
        {
            "name": "confirmed",
            "sql": "SELECT * FROM d WHERE state = 'sale'",
            "source": "sale.order",
            "mine": True,
        },
        {"name": "a", "sql": "SELECT * FROM b"},
        {"name": "b", "sql": "SELECT * FROM a"},
        {"name": "other", "sql": "SELECT * FROM d", "source": "purchase.order"},
    ]
    tables, errors = derived.resolve(STORE, definitions)
    assert tables["total"].collect()["t"].to_list() == [40.0]
    assert errors["a"].startswith("a cycle") and "a" not in tables
    assert "not in your scope" in errors["other"]


def test_a_derived_table_in_polars_reads_the_others():
    definitions = [
        {
            "name": "confirmed",
            "sql": "SELECT * FROM d WHERE state = 'sale'",
            "source": "sale.order",
        },
        {
            "name": "big",
            "language": "polars",
            "sql": 'd_next = tables["confirmed"].filter(pl.col("amount") > 15)',
        },
    ]
    tables, errors = derived.resolve(STORE, definitions)
    assert errors == {} and tables["big"].collect()["id"].to_list() == [3]


def test_a_tile_reads_a_derived_table_and_says_which_filters_it_lacks():
    from kpiten_core import tiles

    store = {
        "sale.order": pl.LazyFrame(
            {
                "id": [1, 2],
                "state": ["sale", "sale"],
                "amount": [10.0, 30.0],
                "user_id": ["Ann", "Bob"],
            }
        )
    }
    definitions = [
        {
            "name": "by_user",
            "source": "sale.order",
            "sql": "SELECT user_id, SUM(amount) AS total FROM d GROUP BY user_id",
        },
    ]
    tables, _errors = derived.resolve(store, definitions)
    line = {
        "kind": "card",
        "name": "Total",
        "content": 'from = "by_user"\nmeasure = "total"\naggregation = "sum"',
    }
    predicates = [pl.col("user_id") == "Ann", pl.col("date_order") > 0]
    result = tiles.exec_tile(line, "sale.order", {**store, **tables}, predicates)
    assert result.value == 10.0  # the user filter applies, the date one cannot
    assert "date_order" in result.note and "by_user" in result.note


def test_a_data_tile_reads_a_derived_table_by_its_name():
    from kpiten_core import tiles

    tables, _errors = derived.resolve(
        STORE,
        [
            {
                "name": "confirmed",
                "source": "sale.order",
                "sql": "SELECT * FROM d WHERE state = 'sale'",
            }
        ],
    )
    store = {**STORE, **tables}
    for content in (
        "SELECT COUNT(*) AS n FROM confirmed",
        'd_next = tables["confirmed"].select(pl.len().alias("n"))',
    ):
        line = {"kind": "data", "name": "n", "content": content}
        result = tiles.exec_tile(line, "sale.order", store, [pl.col("amount") > 15])
        assert result.df["n"].to_list() == [1]  # filtered like the tile : id 3 only


def test_a_monthly_graph_draws_its_trend_ahead():
    import datetime as dt

    from kpiten_core import tiles

    store = {
        "sale.order": pl.LazyFrame(
            {
                "date_order": [dt.date(2026, m, 10) for m in range(1, 7)],
                "amount": [10.0, 12, 14, 16, 18, 20],
            }
        )
    }
    line = {
        "kind": "graph",
        "name": "Monthly",
        "content": 'type = "line"\nby = "date_order"\ngrain = "month"\n'
        'measure = "amount"\ntrend = 3',
    }
    chart = tiles.exec_tile(line, "sale.order", store, []).chart
    trend = chart.trend
    assert trend.height == 9 and trend["amount"].to_list()[-1] == 26.0
    assert trend["date_order"].to_list()[-1] == dt.date(2026, 9, 1)
    assert len(chart and tiles.TileResult("graph", "g", chart=chart).figure.data) == 2
