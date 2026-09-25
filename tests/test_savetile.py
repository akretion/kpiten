"""A new KPI from a tile and the filters it is seen with."""

import pytest

from kpiten_core import savetile, serial

CONFIG = {"dimensions": [{"name": "user_id"}, {"name": "team_id"}]}


def test_the_dimensions_chosen_become_sql():
    conditions = savetile.dimension_conditions(
        CONFIG, {"user_id": ["Marie", "L'Ami"], "team_id": []}, {"user_id", "state"}
    )
    assert conditions == ["\"user_id\" IN ('Marie', 'L''Ami')"]


def test_the_where_of_the_tile_is_kept():
    line = {
        "kind": "card",
        "model": "sale.order",
        "content": "where = \"state = 'sale'\"",
    }
    definition = savetile.new_definition(line, ["amount_untaxed > 2000"])
    assert serial.loads(definition)["where"] == (
        "(state = 'sale') AND (amount_untaxed > 2000)"
    )


def test_a_union_gets_the_names_of_its_mapping():
    content = serial.dumps(
        {
            "union_model": "purchase.order",
            "mapping": {
                "sale.order": {"partner_id": "Partner", "amount_untaxed": "Amount"},
                "purchase.order": {"partner_id": "Partner", "amount_untaxed": "Amount"},
            },
        }
    )
    line = {"kind": "union", "model": "sale.order", "content": content}
    definition = savetile.new_definition(line, ['"amount_untaxed" > 10'])
    assert serial.loads(definition)["where"] == '"Amount" > 10'
    with pytest.raises(ValueError, match="state"):
        savetile.new_definition(line, ["state = 'sale'"])


def test_a_data_tile_has_no_where_and_from_is_the_table():
    with pytest.raises(ValueError):
        savetile.new_definition({"kind": "data", "content": "d_next = d"}, ["x = 1"])
    line = {
        "kind": "graph",
        "model": "sale.order",
        "content": 'from = "sale.order.line"',
    }
    assert savetile.tile_table(line) == "sale.order.line"
