import datetime

import polars as pl
import pytest

from kpiten_core import sandbox
from marimo_kpiten import recipes
from marimo_kpiten.recipes import Recipe

TODAY = datetime.date.today()
DAY = datetime.timedelta(days=1)
FRAME = pl.DataFrame(
    {
        "state": ["purchase", "purchase", "done", "draft", "purchase", "done"],
        "buyer": ["Ann", "Bob", "Ann", "Bob", "Cid", "Ann"],
        "country": ["FR", "FR", "BR", "BR", "FR", "FR"],
        "amount": [500.0, 300.0, 150.0, 999.0, 30.0, 20.0],
        "date": [TODAY - DAY, TODAY - 2 * DAY, TODAY - 40 * DAY] * 2,
    }
).lazy()


def run(**kwargs):
    recipe = Recipe(**kwargs)
    assert recipes.missing(recipe) is None
    return recipes.compute(recipe, FRAME)


def test_a_ranking_is_the_biggest_groups_first():
    result = run(output="ranking", measure="amount", group_by="buyer", top=2)
    assert result.columns == ["buyer", "Sum of amount"]
    assert result.rows() == [("Bob", 1299.0), ("Ann", 670.0)]  # the top 2 of 3


def test_a_filter_keeps_the_chosen_values_and_the_share_adds_up_to_100():
    result = run(
        output="table",
        measure="amount",
        group_by="buyer",
        filter_column="state",
        filter_values=["purchase", "done"],
        add_share=True,
    )
    assert result["buyer"].to_list() == ["Ann", "Bob", "Cid"]  # draft is out
    assert result["Cumulative %"][-1] == pytest.approx(100, abs=0.2)
    assert result["Share %"][0] == pytest.approx(670 / 1000 * 100, abs=0.1)


def test_a_trend_is_one_point_per_period_in_order():
    result = run(output="trend", measure="amount", date="date", grain="month")
    assert result.columns == ["Period", "Sum of amount"]
    assert result["Period"].is_sorted()
    assert result["Sum of amount"].sum() == pytest.approx(1999.0)
    assert (
        run(output="trend", aggregation="count", date="date", grain="year")[
            "Rows"
        ].sum()
        == 6
    )


def test_a_pivot_has_a_column_per_value():
    result = run(
        output="pivot", measure="amount", group_by="buyer", columns_by="country"
    )
    assert set(result.columns) == {"buyer", "FR", "BR"}
    ann = result.filter(pl.col("buyer") == "Ann").row(0, named=True)
    assert (ann["FR"], ann["BR"]) == (520.0, 150.0)


def test_a_pivot_with_too_many_columns_is_refused():
    many = pl.DataFrame(
        {"a": ["x"] * 30, "b": [str(i) for i in range(30)], "v": [1.0] * 30}
    )
    recipe = Recipe(output="pivot", measure="v", group_by="a", columns_by="b")
    with pytest.raises(ValueError, match="too many values"):
        recipes.compute(recipe, many.lazy())


def test_a_card_compares_with_the_period_before():
    recipe = Recipe(output="card", measure="amount", date="date", period="last 30 days")
    card = recipes.card(recipe, FRAME)
    # the last 30 days : the rows of 1 and 2 days ago (500 + 300 + 999 + 30) ; the 30 days
    # before them hold the rows of 40 days ago (150 + 20)
    assert card.value == 1829.0
    assert card.previous == 170.0
    assert card.change == pytest.approx((1829 - 170) / 170 * 100)
    # without a period : the whole table, and nothing to compare with
    whole = recipes.card(Recipe(output="card", measure="amount"), FRAME)
    assert whole.value == 1999.0
    assert whole.previous is None and whole.change is None


def test_counting_needs_no_measure_and_a_missing_choice_is_told():
    assert run(output="card", aggregation="count").item() == 6
    assert "measure" in recipes.missing(Recipe(output="card", aggregation="sum"))
    assert "group" in recipes.missing(Recipe(output="ranking", measure="amount"))
    assert "pivot" in recipes.missing(
        Recipe(output="pivot", measure="amount", group_by="buyer")
    )


def test_the_code_of_every_recipe_passes_the_sandbox():
    for output in recipes.OUTPUTS:
        recipe = Recipe(
            output=output,
            measure="amount",
            group_by="buyer",
            columns_by="country",
            date="date",
            filter_column="state",
            filter_values=["done"],
            add_share=True,
        )
        code = recipes.polars_code(recipe, (TODAY - 30 * DAY, TODAY))
        sandbox.check(code)  # nothing a sandbox refuses
        assert code.startswith("d_next = d.filter(")


def test_a_value_with_a_quote_cannot_leave_the_string():
    recipe = Recipe(
        output="table",
        measure="amount",
        group_by="buyer",
        filter_column="state",
        filter_values=['done"]).collect() #'],
    )
    result = recipes.compute(recipe, FRAME)
    assert result.height == 0  # a value that matches nothing, and no injected code


def highlighted(html: str) -> int:
    return html.count(recipes.HIGHLIGHT_COLOR)


def test_highlights_put_the_right_cells_in_relief():
    frame = pl.DataFrame({"vendor": list("ABCD"), "spend": [500.0, 300.0, 150.0, 50.0]})
    html = lambda mode, value: recipes.styled(
        frame, mode, value
    ).as_raw_html()  # noqa: E731
    assert highlighted(html("none", 0)) == 0
    assert highlighted(html("share", 25)) == 2  # 500 and 300 are 50 % and 30 % of 1000
    assert highlighted(html("share", 60)) == 0
    assert highlighted(html("top", 1)) == 1
    assert highlighted(html("top", 3)) == 3
    assert highlighted(html("above_average", 0)) == 2  # the mean is 250
    assert "background-color" in html("heatmap", 0)  # colored by size


def test_the_share_columns_are_not_highlighted():
    frame = pl.DataFrame(
        {"vendor": ["A", "B"], "Sum": [90.0, 10.0], "Share %": [90.0, 10.0]}
    )
    html = recipes.styled(frame, "above_average").as_raw_html()
    assert highlighted(html) == 1  # only the Sum of A


def test_a_share_keeps_one_decimal_whatever_its_size():
    frame = pl.DataFrame(
        {"v": ["A", "B"], "Sum": [1104.0, 99.0], "Share %": [11.04, 9.9]}
    )
    html = recipes.styled(frame).as_raw_html()
    assert "11,0<" in html and "9,9<" in html  # not 11 and 9,90


# ---- the new functions : each one is off until kt.config turns it on
from kpiten_core import config  # noqa: E402

SPEND = pl.DataFrame({"vendor": list("ABCD"), "spend": [500.0, 300.0, 150.0, 50.0]})


def cells(frame, mode, value):
    return recipes.cell_fills(frame, mode, value)


def test_the_new_highlights_are_offered_only_when_their_feature_is_on():
    try:
        config.set_config({})
        assert set(recipes.highlights()) == set(recipes.HIGHLIGHTS)
        config.set_config({"features": {"alerts": True}})
        offered = recipes.highlights()
        assert "alert_above" in offered and "alert_below" in offered
        assert "outliers" not in offered and "pareto" not in offered
        config.set_config({"features": {"outliers": True, "concentration": True}})
        assert {"outliers", "pareto"} <= set(recipes.highlights())
    finally:
        config.set_config({})


def test_an_alert_puts_the_values_beyond_the_threshold_in_red():
    above = cells(SPEND, "alert_above", 200)
    assert set(above) == {("spend", 0), ("spend", 1)}  # 500 and 300
    assert set(above.values()) == {recipes.RED}
    assert set(cells(SPEND, "alert_below", 100)) == {("spend", 3)}  # 50


def test_an_outlier_is_far_from_the_average():
    frame = pl.DataFrame({"v": list("abcdefghij"), "n": [10.0] * 9 + [1000.0]})
    fills = cells(frame, "outliers", 2)
    assert set(fills) == {("n", 9)}
    assert fills[("n", 9)] == recipes.ORANGE
    assert cells(SPEND, "outliers", 5) == {}  # nothing is 5 deviations away


def test_pareto_puts_in_green_the_groups_that_make_most_of_the_total():
    frame = pl.DataFrame(
        {
            "vendor": list("ABCD"),
            "spend": [500.0, 300.0, 150.0, 50.0],
            "Share %": [50.0, 30.0, 15.0, 5.0],
            "Cumulative %": [50.0, 80.0, 95.0, 100.0],
        }
    )
    fills = cells(frame, "pareto", 80)
    assert set(fills) == {("spend", 0), ("spend", 1)}  # A and B : 80 % between them
    assert set(fills.values()) == {recipes.GREEN}
    # a Pareto needs the shares : the code adds them by itself
    code = recipes.polars_code(
        Recipe(output="table", measure="amount", group_by="buyer", highlight="pareto")
    )
    assert "Cumulative %" in code


def test_the_relief_of_the_table_and_of_the_export_is_the_same_cells():
    html = recipes.styled(SPEND, "alert_above", 200).as_raw_html()
    assert html.count(recipes.RED) == len(cells(SPEND, "alert_above", 200)) == 2


def test_concentration_is_told_only_when_the_feature_is_on():
    recipe = Recipe(output="ranking", measure="amount", group_by="buyer", top=2)
    try:
        config.set_config({})
        assert recipes.concentration(recipe, FRAME) is None
        config.set_config({"features": {"concentration": True}})
        text = recipes.concentration(recipe, FRAME)
        # Bob 1299, Ann 670, Cid 30 : the 3 make all of it, 2 of them make 80 %
        assert "3 largest of 3 groups make 100 %" in text
        assert "2 of them make 80 %" in text
        card = Recipe(output="card", measure="amount")
        assert recipes.concentration(card, FRAME) is None  # a card has no groups
    finally:
        config.set_config({})


def test_a_list_of_records_links_to_odoo_only_when_the_feature_is_on():
    from marimo_kpiten import ui

    class Backend:
        def get_records_action_id(self, model):
            return 488

    try:
        config.set_config({})
        assert (
            ui.records_link(Backend(), "http://odoo", "purchase.order", [1, 2]) is None
        )
        config.set_config({"features": {"open_in_odoo": True}})
        link = ui.records_link(Backend(), "http://odoo", "purchase.order", [1, 2])
        assert "http://odoo/odoo/action-488?active_ids=1,2" in link.text
        assert "Open these 2 records in Odoo" in link.text
        assert ui.records_link(Backend(), "http://odoo", "purchase.order", []) is None
    finally:
        config.set_config({})


# ---- a KPI as a tile of a dashboard, and to refine with the AI
from kpiten_core import tiles  # noqa: E402


def as_tile(recipe):
    """What a dashboard does with the tile : run its definition on the rows of the user."""
    definition = recipes.tile_definition(recipe)
    return tiles.dataframe_case(definition, "t", {"t": FRAME}, [])


def test_a_saved_tile_computes_the_same_table_as_the_kpi():
    for output in ("ranking", "table", "pivot"):
        recipe = Recipe(
            output=output,
            measure="amount",
            group_by="buyer",
            columns_by="country",
            filter_column="state",
            filter_values=["purchase", "done"],
            add_share=True,
        )
        expected = recipes.compute(recipe, FRAME)
        got = as_tile(recipe)
        got = got.collect() if hasattr(got, "collect") else got
        assert got.rows() == expected.rows(), output


def test_the_definition_of_a_tile_starts_the_way_a_data_tile_must():
    definition = recipes.tile_definition(
        Recipe(output="ranking", measure="amount", group_by="buyer")
    )
    first_line = definition.partition("\n")[0]
    # a data tile reads its output and input names on its first line
    assert first_line == "d_next = d"
    assert first_line.split(" ")[0] == "d_next" and first_line.split(" ")[2] == "d"
    sandbox.check(definition)


def test_the_period_of_the_kpi_is_not_repeated_in_the_tile():
    recipe = Recipe(
        output="trend", measure="amount", date="date", period="last 30 days"
    )
    assert "is_between" in recipes.polars_code(recipe, recipes.window_of(recipe))
    assert "is_between" not in recipes.tile_definition(recipe)  # the panel has its own


def test_the_ai_is_given_the_code_of_the_kpi_to_refine():
    recipe = Recipe(output="ranking", measure="amount", group_by="buyer")
    seed = recipes.seed_messages(recipe)
    assert [m["role"] for m in seed] == ["user", "assistant"]
    assert recipes.polars_code(recipe) in seed[0]["content"]
