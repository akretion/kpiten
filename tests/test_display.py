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


def spaced(text: str) -> str:
    """`1 234` as the tables write it (a narrow no-break space)."""
    return text.replace(" ", numfmt.THOUSANDS)


def test_a_decimal_of_a_table_is_whole_unless_it_is_below_10():
    assert numfmt.format_quantity(4542884798.35) == spaced("4 542 884 798")
    assert numfmt.format_quantity(3116.4) == spaced("3 116")
    assert numfmt.format_quantity(-1234.6) == spaced("-1 235")
    assert numfmt.format_quantity(6.756) == "6,76"  # below 10 : the decimals stay
    assert numfmt.format_quantity(0.42) == "0,42"
    assert numfmt.format_quantity(-3.5) == "-3,50"
    assert numfmt.format_quantity(12.0) == "12"


def test_tables_format_the_quantities_only():
    df = pl.DataFrame(
        {
            "Customer": ["A", "B"],
            "Revenue": [4542884798.35, None],
            "Average": [6.756, 0.42],
            "Orders": [12345, 7],
            "id": [1001, 1002],
            "date_order.year": [2025, 2026],
        }
    )
    html = gt_table(df, PALETTE).as_raw_html()
    assert spaced("4 542 884 798<") in html  # rounded to the unit, thousands
    assert "798,35" not in html.replace(numfmt.THOUSANDS, " ")
    assert "6,76" in html and "0,42" in html  # below 10 : the decimals stay
    assert spaced("12 345") in html  # integers
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


def test_period_options_follow_the_data():
    D = datetime.date
    today = D(2026, 9, 19)

    four_years = (D(2022, 9, 19), D(2026, 9, 18))
    options = filters.date_options(four_years, today)
    assert list(options) == [
        "", "last 7 days", "last 30 days", "last 90 days", "last 180 days",
        "last 365 days", "year to date", "2025", "2024", "2023", "2022",
    ]  # fmt: skip
    assert filters.default_date_option(options, four_years, today) == "last 90 days"

    months = filters.date_options((D(2026, 1, 10), D(2026, 9, 18)), today)
    assert "2026-01" in months and "2025" not in months  # months, not years
    assert "last 365 days" not in months  # longer than the data

    old = (D(2023, 1, 1), D(2024, 6, 30))
    stale = filters.date_options(old, today)
    assert "last 7 days" not in stale and "2024-06" in stale
    assert filters.default_date_option(stale, old, today) == ""  # full range

    assert (
        filters.date_options(None) == filters.DATE_OPTIONS
    )  # no date : the static list


def test_calendar_periods_and_their_previous_period():
    D = datetime.date
    assert date_filter.bounds_for_option("2024") == (D(2024, 1, 1), D(2024, 12, 31))
    assert date_filter.bounds_for_option("2024-02") == (D(2024, 2, 1), D(2024, 2, 29))
    assert filters.previous_bounds(
        D(2024, 2, 1) and (D(2024, 2, 1), D(2024, 2, 29))
    ) == (
        D(2024, 1, 1),
        D(2024, 1, 31),
    )
    assert filters.previous_bounds((D(2026, 1, 1), D(2026, 1, 31))) == (
        D(2025, 12, 1),
        D(2025, 12, 31),
    )


def test_date_range_of_the_panel_rows():
    D = datetime.date
    store = {
        "orders": pl.DataFrame({"date_order": [D(2024, 3, 1), D(2025, 5, 2)]}),
        "lines": pl.DataFrame({"order_id.date_order": [D(2023, 7, 9)], "qty": [1]}),
        "other": pl.DataFrame({"x": [1]}),
    }
    config = {"date": {"field": ["date_order", "order_id.date_order"]}}
    assert filters.date_range(store, config) == (D(2023, 7, 9), D(2025, 5, 2))
    assert filters.date_range(store, {}) is None


def test_hidden_columns_are_the_key_of_the_drill_down():
    df = pl.DataFrame(
        {"Product": ["A", "B"], "Revenue": [10, 20], "__product_id_": [7, 8]}
    )
    visible, keys = tiles.split_keys(df)
    assert visible.columns == ["Product", "Revenue"]  # the table does not show them
    assert keys == [{"product_id_": 7}, {"product_id_": 8}]
    assert tiles.split_keys(pl.DataFrame({"x": [1]}))[1] is None


def test_drill_down_runs_on_the_rows_of_the_tile_with_the_key():
    lines = pl.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "product_id_": [7, 7, 8, 7],
            "state": ["sale", "draft", "sale", "sale"],
            "price_subtotal": [10.0, 99.0, 5.0, 20.0],
        }
    )
    line = {
        "name": "Top",
        "drill": (
            "d_next = d\n"
            'd_next = d_next.filter(pl.col("state") == "sale")\n'
            'd_next = d_next.filter(pl.col("product_id_") == key["product_id_"])\n'
            'd_next = d_next.select([pl.col("id"), pl.col("price_subtotal").alias("Revenue")])'
        ),
    }
    result = tiles.exec_drill(line, "l", {"l": lines}, [], {"product_id_": 7})
    assert result.df["Revenue"].to_list() == [10.0, 20.0]  # product 7, confirmed only
    assert result.label == "Top : detail"
    # the panel filters are kept, the key is plain values only, a tile needs a drill
    kept = tiles.exec_drill(
        line, "l", {"l": lines}, [pl.col("id") > 1], {"product_id_": 7}
    )
    assert kept.df["Revenue"].to_list() == [20.0]
    with pytest.raises(tiles.TileError):
        tiles.exec_drill(line, "l", {"l": lines}, [], {"product_id_": [7]})
    with pytest.raises(tiles.TileError):
        tiles.exec_drill({"name": "x"}, "l", {"l": lines}, [], {})
