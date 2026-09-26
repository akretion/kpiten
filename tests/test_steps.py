import polars as pl
import pytest

from derived_kpiten import RESULT, render, split, trace

SQL = """WITH
-- Étape 1 : les commandes confirmées
confirmed AS (SELECT * FROM d WHERE state IN ('sale', 'done') AND amount > 10),
-- Step 2 : the lines of the orders
lines AS (SELECT o.id, o.user_id, o.amount, l.qty FROM confirmed o JOIN line l ON l.order_id = o.id),
by_user AS (SELECT user_id, SUM(amount) AS total FROM lines GROUP BY user_id)
-- the best first
SELECT * FROM by_user ORDER BY total DESC LIMIT 1
"""


@pytest.fixture
def tables():
    return {
        "d": pl.DataFrame(
            {
                "id": [1, 2, 3, 4],
                "state": ["sale", "done", "draft", "sale"],
                "amount": [100.0, 50.0, 70.0, 5.0],
                "user_id": ["Ann", "Bob", "Ann", "Bob"],
            }
        ),
        "line": pl.DataFrame({"order_id": [1, 1, 2], "qty": [1, 2, 3]}),
    }


def test_split_one_step_per_cte_with_its_words():
    steps = split(SQL)
    assert [s.name for s in steps] == ["confirmed", "lines", "by_user", RESULT]
    assert [s.kind for s in steps] == ["filter", "join", "group", "sort"]
    # the numbering of the comment is left out : the place of the step gives it
    assert steps[0].comment == "les commandes confirmées"
    assert steps[1].comment == "the lines of the orders"
    assert steps[2].comment == ""
    assert steps[3].comment == "the best first"
    assert steps[1].sources == ["confirmed", "line"]
    assert "WITH" not in steps[3].sql


def test_a_query_without_cte_is_one_step():
    steps = split("SELECT *, amount * 2 AS twice FROM d")
    assert [(s.name, s.kind) for s in steps] == [(RESULT, "compute")]


def test_trace_counts_the_rows_and_the_columns(tables):
    results = trace(split(SQL), tables, detail=True)
    confirmed, lines, by_user, result = results
    assert (confirmed.rows_in, confirmed.rows_out) == (4, 2)
    # each condition alone : the state removes the draft, the amount the small order
    assert [t["removed"] for t in confirmed.detail["filter"]["terms"]] == [1, 1]
    # 2 orders, 3 lines : the join multiplies the rows
    join = lines.detail["join"][0]
    assert (join["rows_before"], join["rows_after"]) == (2, 3)
    assert lines.columns_added == ["qty"]
    assert by_user.detail["group"]["groups"] == 2
    assert result.rows_out == 1
    assert result.sample["total"].to_list() == [200.0]  # Ann's order counted twice


def test_the_sql_is_checked(tables):
    with pytest.raises(ValueError):
        trace(split("SELECT * FROM read_parquet('/etc/x.parquet')"), tables)
    with pytest.raises(ValueError):
        split("DELETE FROM d")


def test_render_shows_the_detail_only_when_asked(tables):
    results = trace(split(SQL), tables, detail=True)
    simple, detailed = render(results), render(results, detail=True)
    assert "les commandes confirmées" in simple
    assert "multiplies the rows" not in simple
    assert "multiplies the rows" in detailed and "<pre>" in detailed
