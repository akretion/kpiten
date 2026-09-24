"""The syntax version 2 (`spec`) : the version 1 converted, the schema checks."""

import pytest

from kpiten_core import serial, spec
from kpiten_core.validate import validate

FIELDS = {"state", "amount_untaxed", "partner_id", "date_order", "product_id"}


def test_a_card_v1_in_v2():
    v1 = {
        "where": "state = 'sale'",
        "best": "product_id",
        "measure": "amount_untaxed",
        "detail": "amount_untaxed",
        "detail_label": "sold",
        "compare": True,
        "good": "down",
        "derive": {"days": "date_order - date_order"},
    }
    assert spec.upgrade(v1, "card") == {
        "version": 2,
        "where": "state = 'sale'",
        "measure": "amount_untaxed",
        "by": "product_id",
        "compare": {"good": "down"},
        "detail": {"measure": "amount_untaxed", "label": "sold"},
        "computed": {"days": "date_order - date_order"},
    }


def test_a_graph_and_a_pivot_v1_in_v2():
    graph = {
        "graph_type": "area",
        "monthly": True,
        "x": {"name": "date_order", "aggregation": "none"},
        "y": {"name": "amount_untaxed", "aggregation": "sum"},
    }
    assert spec.upgrade(graph, "graph") == {
        "version": 2,
        "type": "area",
        "by": "date_order",
        "grain": "month",
        "measure": "amount_untaxed",
        "aggregation": "sum",
    }
    pivot = {
        "index": "partner_id",
        "column": "date_order.year",
        "measure": "amount_untaxed",
    }
    assert spec.upgrade(pivot, "pivot") == {
        "version": 2,
        "rows": "partner_id",
        "columns": "date_order.year",
        "measure": "amount_untaxed",
    }


def test_a_v1_definition_is_read_as_v2_the_union_as_written():
    text = 'index = "partner_id"\ncolumn = "state"\nmeasure = "amount_untaxed"\n'
    assert spec.load(text, "pivot")["rows"] == "partner_id"
    union = 'union_model = "purchase.order"\n'
    assert spec.load(union, "union") == {"union_model": "purchase.order"}


@pytest.mark.parametrize(
    "definition, kind, message",
    [
        ({"version": 2, "measure": "amount_untaxed"}, "graph", "Missing key 'by'"),
        ({"version": 2, "aggregation": "sum"}, "card", "needs a 'measure'"),
        ({"version": 2, "measure": "nope", "aggregation": "sum"}, "card", "'nope'"),
        ({"version": 2, "decimals": "2"}, "card", "must be a int"),
        ({"version": 2, "compare": {"good": "left"}}, "card", "must be one of"),
        ({"version": 2, "best": "state"}, "card", "Unknown key 'best'"),
        ({"version": 2, "computed": {"d": "x + y"}}, "card", "'<date> - <date>'"),
        ({"version": 2}, "union", "no version 2"),
        ({"version": 3}, "card", "Unknown version"),
    ],
)
def test_the_schema_says_what_is_wrong(definition, kind, message):
    messages = validate(definition, kind, FIELDS)
    assert any(message in m for m in messages), messages


def test_every_v1_definition_converted_is_a_valid_v2_one():
    """The tiles of kpiten_kpi_essential and kpiten_kpi (the xml of kpiten-addons,
    next to this repository) : no message once converted."""
    import pathlib
    import xml.etree.ElementTree as ET

    addons = pathlib.Path(__file__).parents[2] / "kpiten-addons"
    files = sorted(addons.glob("kpiten_kpi*/data/*.xml"))
    if not files:
        pytest.skip("kpiten-addons is not next to kpiten-core")
    checked = 0
    for path in files:
        for record in ET.parse(path).iter("record"):
            fields = {f.get("name"): f.text for f in record.iter("field")}
            kind, text = fields.get("kind"), fields.get("definition")
            if kind not in spec.KINDS or not text:
                continue
            v2 = spec.load(text, kind)
            # the round trip through TOML : what a migration writes
            v2 = serial.loads(serial.dumps(v2))
            assert spec.validate(v2, kind) == [], (path.name, record.get("id"))
            checked += 1
    assert checked > 20
