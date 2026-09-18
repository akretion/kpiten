"""Links from a table tile to the Odoo record."""

import polars as pl
import pytest

from kpiten_core import links, tiles
from kpiten_core.gtable import gt_table

PALETTE = {
    "surface_hex": "#000",
    "text": "#fff",
    "thead": "#111",
    "border_hex": "#222",
    "row_line": "#333",
    "accent": "#00dc82",
}


@pytest.fixture(autouse=True)
def odoo_url():
    links.set_odoo_url("http://odoo.test:8069/")
    yield
    links.set_odoo_url("")


def test_base_url_is_kept_without_trailing_slash():
    assert links.get_odoo_url() == "http://odoo.test:8069"


def test_a_link_to_odoo_is_drawn_as_a_link():
    out = links.link_html(
        "[Thomas Simon](http://odoo.test:8069/odoo/sale.order/12)", "#0f0"
    )
    assert out == (
        '<a href="http://odoo.test:8069/odoo/sale.order/12" target="_blank" '
        'rel="noopener noreferrer" style="color: #0f0">Thomas Simon</a>'
    )


def test_the_label_is_data_and_is_escaped():
    out = links.link_html(
        '[<img src=x onerror="alert(1)">](http://odoo.test:8069/odoo/x/1)'
    )
    assert "<img" not in out and "&lt;img" in out


def test_brackets_and_parentheses_in_a_label_are_kept():
    out = links.link_html(
        "[Imprimerie [Est] (Nord)](http://odoo.test:8069/odoo/sale.order/3)"
    )
    assert out.endswith(">Imprimerie [Est] (Nord)</a>")


@pytest.mark.parametrize(
    "value",
    [
        "[x](http://evil.test/odoo/sale.order/1)",  # not Odoo
        "[x](http://odoo.test:8069.evil.test/a)",  # looks like Odoo
        "[x](javascript:alert(1))",
        "plain text",
    ],
)
def test_only_links_to_odoo_are_followed(value):
    assert "<a " not in links.link_html(value)


def test_no_link_without_a_known_odoo_url():
    links.set_odoo_url("")
    assert "<a " not in links.link_html("[x](http://odoo.test:8069/odoo/sale.order/1)")


def test_link_columns_and_the_table():
    df = pl.DataFrame(
        {
            "Customer": ["[A](http://odoo.test:8069/odoo/sale.order/1)", None],
            "Name": ["[not](a link", "b"],
            "Revenue": [1.5, 2.5],
        }
    )
    assert links.link_columns(df) == ["Customer"]
    html = gt_table(df, PALETTE).as_raw_html()
    assert 'href="http://odoo.test:8069/odoo/sale.order/1"' in html
    assert "[not](a link" in html  # a text column stays text


def test_a_data_snippet_builds_its_links_from_odoo_url():
    df = pl.DataFrame({"id": [7, 8], "partner_id": ["Alice", "Bob"]})
    code = (
        "d_next = d \\n"
        "d_next = d_next.select([pl.concat_str([pl.lit('['), pl.col('partner_id'), "
        "pl.lit(']('), pl.lit(odoo_url), pl.lit('/odoo/sale.order/'), "
        "pl.col('id').cast(pl.String), pl.lit(')')]).alias('Customer')])"
    ).replace("\\n", "\n")
    res = tiles.exec_tile(
        {"kind": "data", "name": "t", "content": code},
        "sale.order",
        {"sale.order": df},
        [],
    )
    assert res.df["Customer"].to_list() == [
        "[Alice](http://odoo.test:8069/odoo/sale.order/7)",
        "[Bob](http://odoo.test:8069/odoo/sale.order/8)",
    ]
    assert links.link_columns(res.df) == ["Customer"]
