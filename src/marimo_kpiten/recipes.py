"""Recurring needs as a few choices : a KPI built without the AI.

The user picks what to compute (a measure, a grouping, a period, a filter...), this module
writes the polars for it and the sandbox of kpiten-core runs it on the table of the user
(the same path as the code of the AI). What is drawn afterwards : `styled` puts a table
in relief with Great Tables (values above X % of the total, the largest, a heat map...).
"""

import dataclasses
import json
from dataclasses import dataclass, field

import polars as pl
from great_tables import GT, loc, style

from kpiten_core import config, filters, numfmt
from kpiten_core.gtable import gt_table, number_columns

from . import ai

OUTPUTS = {
    "card": "Card : one number",
    "ranking": "Ranking : the top N",
    "trend": "Trend over time",
    "table": "Table by group",
    "pivot": "Pivot table",
}
AGGREGATIONS = {
    "sum": "Sum",
    "mean": "Average",
    "count": "Number of rows",
    "min": "Minimum",
    "max": "Maximum",
    "n_unique": "Distinct values",
}
GRAINS = {"month": "1mo", "quarter": "1q", "year": "1y"}
HIGHLIGHTS = {
    "none": "No highlight",
    "share": "Share of the total at least X %",
    "top": "The X largest values",
    "above_average": "Above the average",
    "heatmap": "Heat map",
}
# the columns `share` adds : not values to highlight
SHARE_COLUMNS = ("Share %", "Cumulative %")
MAX_PIVOT_COLUMNS = 12
YELLOW, RED, ORANGE, GREEN = "#ffe08a", "#ffc9c9", "#ffd8a8", "#b2f2bb"
HEAT = "#f59f00"  # the dark end of the heat map
HIGHLIGHT_COLOR = YELLOW
# highlights that come with a new feature of `kt.config` : key -> (feature, label)
FEATURE_HIGHLIGHTS = {
    "alert_above": ("alerts", "Alert : the values above X"),
    "alert_below": ("alerts", "Alert : the values below X"),
    "outliers": ("outliers", "Outliers : X standard deviations from the average"),
    "pareto": ("concentration", "Pareto : the groups that make X % of the total"),
}
CONCENTRATION_TOP, CONCENTRATION_SHARE = 3, 80
# what the value of a highlight is : mode -> (default, what it is)
HIGHLIGHT_VALUE = {
    "share": (20, "X = % of the total"),
    "top": (3, "X = how many"),
    "alert_above": (1000, "Threshold"),
    "alert_below": (0, "Threshold"),
    "outliers": (2, "Standard deviations"),
    "pareto": (80, "% of the total"),
}
# a light palette for `gtable.gt_table` (the notebooks are light)
LIGHT = {
    "surface_hex": "#ffffff",
    "text": "#24292f",
    "thead": "#f3f4f6",
    "border_hex": "#d8dee4",
    "row_line": "#eaeef2",
    "accent": "#0a6ebd",
}


@dataclass
class Recipe:
    output: str = "ranking"
    measure: str | None = None  # a column ; none : count the rows
    aggregation: str = "sum"
    group_by: str | None = None
    columns_by: str | None = None  # pivot : the column that becomes the columns
    date: str | None = None
    grain: str = "month"
    period: str = ""  # a period of `filters.date_options` ("" : all the dates)
    filter_column: str | None = None
    filter_values: list = field(default_factory=list)
    top: int = 10
    add_share: bool = False  # ranking / table : share of the total and cumulative share
    highlight: str = "none"
    highlight_value: float = 20


def _q(text: str) -> str:
    """A string as python source (the code is shown to the user, and run)."""
    return json.dumps(text)


def value_label(recipe: Recipe) -> str:
    """The name of the computed column."""
    if recipe.aggregation == "count" or not recipe.measure:
        return "Rows"
    return f"{AGGREGATIONS[recipe.aggregation]} of {recipe.measure}"


def title(recipe: Recipe) -> str:
    what = value_label(recipe)
    if recipe.output == "trend":
        return f"{what} per {recipe.grain}"
    if recipe.output == "pivot":
        return f"{what} by {recipe.group_by} and {recipe.columns_by}"
    if recipe.output == "card":
        return what
    return f"{what} by {recipe.group_by}"


def _aggregation(recipe: Recipe) -> str:
    """The polars expression of the measure, named."""
    alias = f".alias({_q(value_label(recipe))})"
    if recipe.aggregation == "count" or not recipe.measure:
        return f"pl.len(){alias}"
    column = f"pl.col({_q(recipe.measure)})"
    if recipe.aggregation == "n_unique":
        return f"{column}.n_unique(){alias}"
    # floats : a decimal column would give a decimal sum, hard to draw and to format
    return f"{column}.cast(pl.Float64).{recipe.aggregation}(){alias}"


def missing(recipe: Recipe) -> str | None:
    """What still has to be chosen, None when the recipe can run."""
    if recipe.aggregation != "count" and not recipe.measure:
        return "Choose a measure (or count the rows)."
    if recipe.output in ("ranking", "table", "pivot") and not recipe.group_by:
        return "Choose what to group by."
    if recipe.output == "pivot" and not recipe.columns_by:
        return "Choose the column of the pivot."
    if recipe.output == "pivot" and recipe.columns_by == recipe.group_by:
        return "The rows and the columns of a pivot are two different columns."
    if recipe.output == "trend" and not recipe.date:
        return "Choose the date column."
    return None


def polars_code(recipe: Recipe, window: tuple | None = None) -> str:
    """The snippet that computes the recipe : `d` in, `d_next` out. `window` restricts the
    date column to a period (`filters.bounds_of_option`)."""
    conditions = []
    if recipe.filter_column and recipe.filter_values:
        values = json.dumps([str(v) for v in recipe.filter_values])
        conditions.append(f"pl.col({_q(recipe.filter_column)}).is_in({values})")
    if window and recipe.date:
        first, last = (f'pl.lit("{day.isoformat()}").str.to_date()' for day in window)
        conditions.append(f"pl.col({_q(recipe.date)}).is_between({first}, {last})")
    source = "d"
    if conditions:
        source += ".filter(" + " & ".join(f"({c})" for c in conditions) + ")"

    agg, value = _aggregation(recipe), _q(value_label(recipe))
    if recipe.output == "card":
        chain = f".select({agg})"
    elif recipe.output == "trend":
        key = (
            f"pl.col({_q(recipe.date)}).dt.truncate({_q(GRAINS[recipe.grain])})"
            f'.alias("Period")'
        )
        chain = f'.group_by({key}).agg({agg}).sort("Period")'
    elif recipe.output == "pivot":
        rows, cols = _q(recipe.group_by), _q(recipe.columns_by)
        chain = (
            f".group_by([{rows}, {cols}]).agg({agg}).collect()"
            f".pivot(on={cols}, index={rows}, values={value}).sort({rows}).head({recipe.top})"
        )
    else:  # ranking, table
        chain = f".group_by({_q(recipe.group_by)}).agg({agg}).sort({value}, descending=True)"
        if recipe.add_share or recipe.highlight == "pareto":
            chain += (
                f".with_columns((pl.col({value}) / pl.col({value}).sum() * 100)"
                f'.round(1).alias("Share %"))'
                '.with_columns(pl.col("Share %").cum_sum().round(1).alias("Cumulative %"))'
            )
        if recipe.output == "ranking":
            chain += f".head({recipe.top})"
    return f"d_next = {source}{chain}"


def compute(recipe: Recipe, frame: pl.LazyFrame, window: tuple | None = None):
    """The table of the recipe, computed by the sandbox on the user's table."""
    result = ai.run(polars_code(recipe, window), frame)
    if recipe.output == "pivot" and result.width - 1 > MAX_PIVOT_COLUMNS:
        raise ValueError(
            f"{result.width - 1} columns : {recipe.columns_by} has too many values for a "
            f"pivot (at most {MAX_PIVOT_COLUMNS}). Filter it, or pick another column."
        )
    return result


@dataclass
class Card:
    value: float | None
    previous: float | None
    label: str

    @property
    def change(self) -> float | None:
        if self.previous in (None, 0) or self.value is None:
            return None
        return (self.value - self.previous) / abs(self.previous) * 100


def card(recipe: Recipe, frame: pl.LazyFrame) -> Card:
    """The number of a card, and the same one for the period before (the change is
    what an Odoo scorecard shows)."""
    window = filters.bounds_of_option(recipe.period) if recipe.period else None
    value = compute(recipe, frame, window).item()
    previous_window = filters.previous_bounds(window)
    previous = (
        compute(recipe, frame, previous_window).item() if previous_window else None
    )
    return Card(value, previous, value_label(recipe))


def plain(frame: pl.DataFrame) -> pl.DataFrame:
    """Decimals as floats : what the tables draw well."""
    decimals = [c for c, t in frame.schema.items() if t.is_decimal()]
    return frame.with_columns(pl.col(decimals).cast(pl.Float64)) if decimals else frame


def highlights() -> dict:
    """The highlights offered : the base ones, and the new ones whose feature is on in
    `kt.config` (alerts, outliers, Pareto)."""
    offered = dict(HIGHLIGHTS)
    for key, (feature, label) in FEATURE_HIGHLIGHTS.items():
        if config.feature(feature):
            offered[key] = label
    return offered


def _heat(fraction: float) -> str:
    """A color from white (0) to the dark end of the heat map (1)."""
    dark = [int(HEAT[i : i + 2], 16) for i in (1, 3, 5)]
    red, green, blue = (round(255 + (d - 255) * fraction) for d in dark)
    return f"#{red:02x}{green:02x}{blue:02x}"


def cell_fills(frame: pl.DataFrame, highlight: str, value: float) -> dict:
    """The cells to put in relief : `{(column, row): color}`. One calculation for the
    table drawn by Great Tables and for the .ods export : they show the same cells."""
    frame = plain(frame)
    integers, decimals = number_columns(frame)
    columns = [c for c in integers + decimals if c not in SHARE_COLUMNS]
    if not columns or highlight in ("none", ""):
        return {}
    numbers = pl.concat([frame[c].cast(pl.Float64) for c in columns]).drop_nulls()
    if numbers.is_empty():
        return {}
    fills: dict = {}

    def mark(test, color):
        for column in columns:
            for row, number in enumerate(frame[column].to_list()):
                if number is not None and test(number):
                    fills[(column, row)] = color

    total, average = numbers.sum(), numbers.mean()
    if highlight == "heatmap":
        low, span = numbers.min(), (numbers.max() - numbers.min()) or 1
        for column in columns:
            for row, number in enumerate(frame[column].to_list()):
                if number is not None:
                    fills[(column, row)] = _heat((number - low) / span)
    elif highlight == "share":
        mark(lambda n: n >= total * value / 100, YELLOW)
    elif highlight == "top":
        # the `value`-th largest number of the table, ties included
        largest = numbers.sort(descending=True)
        limit = largest[min(max(int(value), 1), len(largest)) - 1]
        mark(lambda n: n >= limit, YELLOW)
    elif highlight == "above_average":
        mark(lambda n: n > average, YELLOW)
    elif highlight == "alert_above":
        mark(lambda n: n > value, RED)
    elif highlight == "alert_below":
        mark(lambda n: n < value, RED)
    elif highlight == "outliers":
        spread = numbers.std()
        if spread:
            mark(lambda n: abs(n - average) > value * spread, ORANGE)
    elif highlight == "pareto" and all(c in frame.columns for c in SHARE_COLUMNS):
        # the groups until the cumulative share crosses `value` % (the first one that does
        # is in) : those that make most of the total
        vital = [
            row
            for row, (cumulative, share) in enumerate(
                zip(frame["Cumulative %"].to_list(), frame["Share %"].to_list())
            )
            if cumulative is not None and cumulative - share < value
        ]
        for column in columns:
            for row in vital:
                fills[(column, row)] = GREEN
    return fills


def styled(frame: pl.DataFrame, highlight: str = "none", value: float = 20) -> GT:
    """The table of a recipe, in relief (`cell_fills` says which cells) with Great
    Tables. Numbers are written as in the tables of the dashboards (`kt.config`)."""
    frame = plain(frame)
    table = gt_table(frame, LIGHT)
    shares = [c for c in SHARE_COLUMNS if c in frame.columns]
    if shares:  # percentages keep one decimal, whatever their size
        table = table.fmt(
            lambda number: "" if number is None else numfmt.format_number(number, 1),
            columns=shares,
        )
    by_color: dict = {}
    for (column, row), color in cell_fills(frame, highlight, value).items():
        by_color.setdefault((column, color), []).append(row)
    weight = "normal" if highlight == "heatmap" else "bold"
    for (column, color), rows in by_color.items():
        table = table.tab_style(
            style=[style.fill(color=color), style.text(weight=weight)],
            locations=loc.body(columns=column, rows=rows),
        )
    return table


def highlight_note(highlight: str, value: float) -> str:
    return {
        "share": f"Highlighted : at least {value:g} % of the total.",
        "top": f"Highlighted : the {value:g} largest values.",
        "above_average": "Highlighted : above the average.",
        "heatmap": "Colored by size.",
        "alert_above": f"In red : the values above {value:g}.",
        "alert_below": f"In red : the values below {value:g}.",
        "outliers": f"In orange : more than {value:g} standard deviations from the average.",
        "pareto": f"In green : the groups that make {value:g} % of the total.",
    }.get(highlight, "")


def concentration(recipe: Recipe, frame: pl.LazyFrame) -> str | None:
    """How concentrated a ranking is : what the biggest groups make of the total, and how
    many groups make most of it. Off unless the feature is on in `kt.config`."""
    if not config.feature("concentration") or recipe.output not in ("ranking", "table"):
        return None
    every_group = dataclasses.replace(
        recipe, output="table", add_share=False, highlight="none"
    )
    if missing(every_group):
        return None
    result = compute(every_group, frame)
    if result.height >= ai.MAX_ROWS:  # cut off : the total would be wrong
        return None
    values = sorted(
        (
            v
            for v in result[value_label(every_group)].cast(pl.Float64).to_list()
            if v and v > 0
        ),
        reverse=True,
    )
    total = sum(values)
    if not total:
        return None
    top = sum(values[:CONCENTRATION_TOP]) / total * 100
    running, needed = 0.0, len(values)
    for count, amount in enumerate(values, 1):
        running += amount
        if running / total * 100 >= CONCENTRATION_SHARE:
            needed = count
            break
    return (
        f"The {min(CONCENTRATION_TOP, len(values))} largest of {len(values)} groups make "
        f"{top:.0f} % of the total ; {needed} of them make {CONCENTRATION_SHARE} %."
    )
