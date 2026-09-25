"""Ask a KPI in words : the filter the model writes, checked and tried on the rows."""

import json

import polars as pl
import pytest

from kpiten_core import anonymize, llm, querychat

PROVIDER = llm.Provider("local", "Local (fake)", "fake", False)
LINE = {"id": 1, "name": "Orders", "kind": "card", "model": "sale.order"}
FRAME = pl.LazyFrame(
    {
        "id": [1, 2, 3],
        "state": ["sale", "draft", "sale"],
        "partner_id": ["Dupont SA", "Martin", "Dupont SA"],
        "partner_id.country_id": [20, 75, 75],
        "amount_untaxed": [100.0, 2500.0, 3000.0],
    }
)


def model(*answers):
    """A fake model : its answers, one per call, and the calls it got."""
    calls = []

    def complete(provider, system, messages):
        calls.append(messages)
        return answers[len(calls) - 1]

    complete.calls = calls
    return complete


def ask(complete, question="?", anon=None):
    return querychat.ask(
        PROVIDER, LINE, FRAME, "the columns", [], question, anon, complete=complete
    )


def test_a_filter_is_checked_tried_and_kept():
    answer = {"action": "filter", "where": "state = 'sale'", "title": "Confirmed"}
    reply = ask(model("```json\n" + json.dumps(answer) + "\n```"))
    assert (reply.action, reply.where, reply.title) == (
        "filter",
        "state = 'sale'",
        "Confirmed",
    )
    assert querychat.apply(FRAME, reply.where).collect()["id"].to_list() == [1, 3]


def test_a_failing_filter_goes_back_once_to_the_model():
    wrong = json.dumps({"action": "filter", "where": "nope = 1"})
    right = json.dumps({"action": "filter", "where": "amount_untaxed > 2000"})
    complete = model(wrong, right)
    reply = ask(complete)
    assert reply.where == "amount_untaxed > 2000"
    assert "That failed" in complete.calls[1][-1]["content"]


def test_no_file_and_no_other_table():
    where = "id IN (SELECT id FROM read_parquet('/data/other/sale.order.parquet'))"
    reply = ask(model(*[json.dumps({"action": "filter", "where": where})] * 2))
    assert reply.action == "none" and reply.error


def test_clear_and_a_plain_answer():
    assert ask(model('{"action": "clear", "answer": "All"}')).action == "clear"
    reply = ask(model("I only narrow the rows."))
    assert (reply.action, reply.where) == ("none", None)


def test_a_dotted_column_is_quoted():
    where = querychat.quote_columns(
        'partner_id.country_id = 75 AND "partner_id.country_id" > 1',
        FRAME.collect_schema().names(),
    )
    assert where == '"partner_id.country_id" = 75 AND "partner_id.country_id" > 1'


def test_the_model_sees_pseudonyms_the_filter_runs_on_real_names():
    anon = anonymize.Anonymizer(
        "sale.order", {"partner_id": {"type": "many2one", "rel": "res.partner"}}
    )
    anon.learn(FRAME, anon.kinds(FRAME.collect_schema()))
    pseudo = anon.hide("Dupont SA")
    assert pseudo != "Dupont SA"
    where = f"partner_id = '{pseudo}'"
    complete = model(json.dumps({"action": "filter", "where": where, "title": pseudo}))
    reply = ask(complete, "only Dupont SA", anon)
    assert "Dupont SA" not in json.dumps(complete.calls)
    assert reply.where == "partner_id = 'Dupont SA'" and reply.title == "Dupont SA"


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2]"])
def test_parse_refuses_what_is_not_an_object(text):
    with pytest.raises(ValueError):
        querychat.parse(text)


# ---- a panel : the tables follow each other through their many2one
ORDERS = pl.LazyFrame({"id": [1, 2, 3], "amount_untaxed": [100.0, 2500.0, 3000.0]})
LINES = pl.LazyFrame(
    {"id": [10, 11, 12, 13], "order_id_": [1, 2, 2, 3], "product_id": list("ABAB")}
)
PANEL = {"sale.order": ORDERS, "sale.order.line": LINES}
RELS = {"sale.order": {}, "sale.order.line": {"order_id": "sale.order"}}


def ids(store, table):
    return sorted(store[table].collect()["id"].to_list())


def test_the_lines_follow_their_orders():
    store, followed = querychat.narrow_store(
        PANEL, {"sale.order": "amount_untaxed > 2000"}, RELS
    )
    assert ids(store, "sale.order") == [2, 3]
    assert ids(store, "sale.order.line") == [11, 12, 13]
    assert followed == {"sale.order.line": ["sale.order"]}


def test_the_orders_follow_their_lines():
    store, followed = querychat.narrow_store(
        PANEL, {"sale.order.line": "product_id = 'A'"}, RELS
    )
    assert ids(store, "sale.order") == [1, 2]
    assert followed == {"sale.order": ["sale.order.line"]}


def test_a_table_out_of_the_panel_does_not_follow():
    store, followed = querychat.narrow_store(
        PANEL, {"sale.order": "id = 1"}, RELS, tables=["sale.order"]
    )
    assert ids(store, "sale.order.line") == [10, 11, 12, 13] and followed == {}


def test_the_panel_filters_are_checked_table_by_table():
    wrong = json.dumps({"action": "filter", "filters": {"res.partner": "id = 1"}})
    right = json.dumps(
        {"action": "filter", "filters": {"sale.order": "amount_untaxed > 2000"}}
    )
    complete = model(wrong, right)
    reply = querychat.ask_panel(
        PROVIDER, "Sales", PANEL, {"sale.order": "…"}, [], "?", complete=complete
    )
    assert reply.filters == {"sale.order": "amount_untaxed > 2000"}
    assert "unknown table" in complete.calls[1][-1]["content"]
