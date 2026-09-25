"""A card checked in Odoo : its conditions as an Odoo domain."""

import datetime

import polars as pl
import pytest

from kpiten_core import odoocheck

ORDERS = pl.LazyFrame(
    {
        "user_id": ["Marie Stourne", "Paul Dupont"],
        "user_id_": [7, 8],
        "state": ["a", "b"],
    }
)


def test_a_name_of_a_many2one_is_its_id_and_sql_leaves_the_empty_ones_out():
    domain = odoocheck.where_domain(
        "\"user_id\" IN ('Marie Stourne') AND state <> 'draft'", ORDERS
    )
    assert domain == [
        "&",
        ("user_id", "in", [7]),
        "&",
        ("state", "!=", "draft"),
        ("state", "!=", False),
    ]


def test_a_computed_column_or_a_function_has_no_domain():
    with pytest.raises(odoocheck.Untranslatable):
        odoocheck.where_domain("days > 3", ORDERS, computed={"days"})
    with pytest.raises(odoocheck.Untranslatable):
        odoocheck.where_domain("lower(state) = 'a'", ORDERS)


def test_the_period_ends_before_the_day_after_and_the_ids_are_ranges():
    period = (datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
    assert odoocheck.period_domain(["date_order", "other"], period, {"date_order"}) == [
        ("date_order", ">=", "2026-07-01"),
        ("date_order", "<", "2026-08-01"),
    ]
    assert odoocheck.id_ranges([9, 1, 2, 3, 5, 10]) == "1-3,5,9-10"
