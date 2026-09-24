"""The schema of the syntax version 2 and the validation of a definition."""

import pytest

from kpiten_spec import spec, validate_display, validate_toml
from kpiten_spec.validate import validate

FIELDS = {"state", "amount_untaxed", "partner_id", "date_order", "product_id"}


@pytest.mark.parametrize(
    "definition, kind, message",
    [
        ({"measure": "amount_untaxed"}, "graph", "Missing key 'by'"),
        ({"aggregation": "sum"}, "card", "needs a 'measure'"),
        ({"measure": "nope", "aggregation": "sum"}, "card", "'nope'"),
        ({"decimals": "2"}, "card", "must be a int"),
        ({"compare": {"good": "left"}}, "card", "must be one of"),
        ({"best": "state"}, "card", "Unknown key 'best'"),  # the version 1
        ({"computed": {"d": "x + y"}}, "card", "'<date> - <date>'"),
        (
            {"type": "pie", "by": "state", "measure": "id", "series": "x"},
            "graph",
            "pie",
        ),
        (
            {
                "rows": "state",
                "columns": "partner_id",
                "measure": "amount_untaxed",
                "aggregation": "mean",
                "table": {"totals": True},
            },
            "pivot",
            "Totals need",
        ),
        ({"version": 2}, "union", "no version 2"),
        ({"version": 3}, "card", "Unknown version"),
    ],
)
def test_the_schema_says_what_is_wrong(definition, kind, message):
    messages = validate(definition, kind, FIELDS)
    assert any(message in m for m in messages), messages


def test_valid_definitions():
    assert validate_toml("where = \"state = 'sale'\"", "card", FIELDS) == []
    graph = 'type = "bar"\nby = "partner_id"\nmeasure = "amount_untaxed"\n'
    assert validate_toml(graph + '[labels]\namount_untaxed = "HT"\n', "graph") == []
    union = 'union_model = "purchase.order"\n[mapping."sale.order"]\nname = "name"\n'
    assert validate_toml(union, "union") == []


def test_the_display_of_a_data_tile():
    sql = (
        "-- a comment before the header\n"
        "-- [labels]\n"
        '-- amount_untaxed = "HT"\n'
        "-- [table]\n"
        "-- totals = true  # a Total row\n"
        "-- a plain comment ends the header\n"
        "SELECT 1 FROM d"
    )
    assert spec.is_sql(sql) and not spec.is_sql("d_next = d")
    assert spec.display(sql) == {
        "labels": {"amount_untaxed": "HT"},
        "table": {"totals": True},
    }
    field = '[table]\nformat = "currency"\n'
    assert spec.display(sql, field)["table"] == {"totals": True, "format": "currency"}
    assert validate_display(sql, field) == []
    assert validate_display(sql, '[table]\nformat = "roman"\n') != []
    assert validate_display(sql, "limit = ") != []  # not TOML : said, not raised
