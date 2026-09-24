from kpiten_spec.edit import set_keys
from kpiten_spec.spec import tomllib

GRAPH = '''# the ten best customers
type = "bar"
by = "partner_id"  # the x axis
measure = "amount_untaxed"
where = """
state = 'sale'
"""

[plotly.layout]  # given as is to plotly
bargap = 0.4
'''


def test_the_keys_changed_only_the_rest_as_it_is_written():
    text = set_keys(
        GRAPH,
        {"by": "user_id", "where": None, "limit": 10, "measure": "amount_untaxed"},
    )
    assert text == """# the ten best customers
type = "bar"
by = "user_id"  # the x axis
measure = "amount_untaxed"
limit = 10

[plotly.layout]  # given as is to plotly
bargap = 0.4
"""
    data = tomllib.loads(text)
    assert data["plotly"]["layout"]["bargap"] == 0.4 and "where" not in data


def test_a_new_definition_and_the_values_escaped():
    text = set_keys(
        "", {"where": 'name = "a#b"', "stacked": True, "from": "sale.order"}
    )
    assert tomllib.loads(text) == {
        "where": 'name = "a#b"',
        "stacked": True,
        "from": "sale.order",
    }
    assert set_keys(text, {"where": None, "stacked": None, "from": None}) == ""
