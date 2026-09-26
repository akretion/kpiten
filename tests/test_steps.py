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


def test_a_query_without_cte_is_cut_by_its_clauses(tables):
    assert [s.name for s in split("SELECT * FROM d")] == [RESULT]
    sql = (
        "SELECT user_id, SUM(amount) AS total FROM d WHERE state = 'sale' "
        "GROUP BY user_id ORDER BY total DESC LIMIT 1"
    )
    steps = split(sql)
    assert [(s.name, s.kind) for s in steps] == [
        ("from", "select"),
        ("where", "filter"),
        ("select", "group"),
        ("order", "sort"),
        (RESULT, "limit"),
    ]
    results = trace(steps, tables, detail=True)
    assert [(r.rows_in, r.rows_out) for r in results] == [
        (4, 4),
        (4, 2),
        (2, 2),
        (2, 2),
        (2, 1),
    ]
    # the detail of a clause is its own : the filter is not measured again later
    assert list(results[1].detail) == ["filter"] and results[3].detail == {}


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


def test_the_ai_writes_the_query_and_fixes_it_once(tables):
    from derived_kpiten import ai

    answers = iter(
        [
            "Here.\n```sql\nSELECT * FROM nowhere\n```",
            "Fixed.\n```sql\nWITH\n-- Step 1 : the sales\n"
            "sales AS (SELECT * FROM d WHERE state = 'sale')\n"
            "SELECT COUNT(*) AS n FROM sales\n```",
        ]
    )
    sent = []

    def complete(provider, system, messages):
        sent.append(messages)
        return next(answers)

    system = ai.system_prompt("sale.order", "id (Int64)", {"line": "qty (Int64)"})
    assert "Step n" in system and '"line" : qty' in system
    answer = ai.ask(None, tables, system, "How many sales ?", complete=complete)
    assert answer.text == "Fixed." and answer.error is None
    assert [r.step.name for r in answer.results] == ["sales", "result"]
    assert "unknown table" in sent[1][-1]["content"]  # the error went back once


def test_a_pasted_answer_with_an_unknown_name_does_not_run(tables):
    from kpiten_core.anonymize import Anonymizer

    from derived_kpiten import ai

    anon = Anonymizer("sale.order")
    known = anon.pseudonym("Salesperson", "Ann")
    pasted = (
        "Here.\n```sql\nSELECT * FROM d WHERE user_id IN "
        f"('{known}', 'Salesperson 9')\n```"
    )
    answer = ai.receive(pasted, tables, anon)
    assert "Salesperson 9" in answer.error and answer.results is None
    answer = ai.receive(pasted.replace(", 'Salesperson 9'", ""), tables, anon)
    assert answer.error is None and "'Ann'" in answer.sql  # revealed, then run
    assert answer.results[-1].rows_out == 2
