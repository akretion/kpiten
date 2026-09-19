"""How numbers, currencies, comparisons and periods are shown."""

import datetime

import polars as pl
import pytest

from kpiten_core import date_filter, filters, numfmt, tiles
from kpiten_core.comparison import color, tone
from kpiten_core.gtable import gt_table

PALETTE = {
    "surface_hex": "#000",
    "text": "#fff",
    "thead": "#111",
    "border_hex": "#333",
    "row_line": "#222",
    "accent": "#0f0",
}


def test_format_number(monkeypatch):
    assert numfmt.format_number(4542884798.35, 2) == "4 542 884 798,35"
    assert numfmt.format_number(12345) == "12 345"
    monkeypatch.setenv("DECIMAL_MARK", ".")
    assert numfmt.format_number(1234.5, 1) == "1 234.5"


def test_tables_format_the_quantities_only():
    df = pl.DataFrame(
        {
            "Customer": ["A", "B"],
            "Revenue": [4542884798.35, None],
            "Orders": [12345, 7],
            "id": [1001, 1002],
            "date_order.year": [2025, 2026],
        }
    )
    html = gt_table(df, PALETTE).as_raw_html()
    assert "4 542 884 798,35" in html  # decimals, thousands
    assert "12 345" in html  # integers
    assert "1001" in html and "2025" in html  # ids and years are not quantities


def test_currency_unit_follows_the_company(monkeypatch):
    def show(unit_config):
        tiles.set_chart_config({"currency": unit_config} if unit_config else {})
        return tiles.format_card_value(1234.6, "sum", {"unit": "currency"})

    try:
        assert show({"symbol": "$", "position": "before"}) == "$1 235"
        assert show({"symbol": "€", "position": "after"}) == "1 235 €"
        assert show(None) == "1 235"  # Odoo did not say : no symbol
    finally:
        tiles.set_chart_config({})


def test_comparison_tone_follows_the_card():
    """`good = "down"` : a fall is green, the arrow still says it fell."""

    def compare(definition, now, before):
        rows = pl.DataFrame({"tag": ["x"] * before})
        return tiles.card_comparison(
            definition, "t", {"t": rows}, now, [pl.col("tag") == "x"]
        )

    up = compare("compare = true\n", 12, 10)
    assert (up["direction"], up["tone"]) == ("up", "good")
    late = compare('compare = true\ngood = "down"\n', 12, 10)
    assert (late["direction"], late["tone"]) == ("up", "bad")
    fall = compare('compare = true\ngood = "down"\n', 8, 10)
    assert (fall["direction"], fall["tone"]) == ("down", "good")
    assert color(fall) == color(up)  # same green
    assert color(late) != color(up)
    assert tone({"direction": "down"}) == "bad"  # no tone : up is good


def test_odoo_relative_periods(monkeypatch):
    """Odoo's "Last 30 Days" is 30 days ending today ; the period before is the
    30 days before it (getRelativeDateDomain)."""

    class Frozen(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 19)

    monkeypatch.setattr(date_filter.datetime, "date", Frozen)
    start, end = date_filter.bounds_for_option("last 30 days")
    assert (start, end) == (Frozen(2026, 8, 21), Frozen(2026, 9, 19))
    assert (end - start).days + 1 == 30
    assert filters.previous_bounds((start, end)) == (
        Frozen(2026, 7, 22),
        Frozen(2026, 8, 20),
    )
    assert date_filter.bounds_for_option("last 7 days")[0] == Frozen(2026, 9, 13)
    assert date_filter.bounds_for_option("last week") == date_filter.bounds_for_option(
        "last 7 days"
    )  # the old names are still understood
    # year to date : the same span one year earlier, not "N days before"
    ytd = date_filter.bounds_for_option("year to date")
    assert ytd == (Frozen(2026, 1, 1), Frozen(2026, 9, 19))
    assert filters.previous_bounds(ytd) == (Frozen(2025, 1, 1), Frozen(2025, 9, 19))
    last_year = date_filter.bounds_for_option("last year")
    assert filters.previous_bounds(last_year) == (
        Frozen(2024, 1, 1),
        Frozen(2024, 12, 31),
    )


def test_validate_good_key():
    from kpiten_core import validate_toml

    assert validate_toml('compare = true\ngood = "down"', "card") == []
    assert validate_toml('good = "sideways"', "card") != []
