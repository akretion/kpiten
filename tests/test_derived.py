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
