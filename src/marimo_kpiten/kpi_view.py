"""How the KPI of a recipe is drawn in a notebook : a card, bars, an area, a table.

`render` runs the recipe (`recipes`) and returns what marimo shows : the title, the chart or
the number, the table in relief, and the polars behind it. Colors are the ones of `kt.config`
(the palette for bars, the fill color for areas).
"""

import re

import altair as alt
import marimo as mo
import polars as pl

from kpiten_core import config, filters, numfmt

from . import ods, recipes

ACCENT = "#0a6ebd"


def _number(value) -> str:
    """A number as the dashboards write it (`kt.config` : format, decimals)."""
    if value is None:
        return "—"
    if isinstance(value, int):
        return numfmt.format_number(value)
    return numfmt.format_quantity(value)


def _simple(frame: pl.DataFrame, key: str, value: str) -> pl.DataFrame:
    """The two columns of a chart under plain names : a column called `a.b` would be read
    by the chart library as a nested field."""
    return recipes.plain(frame).select(
        pl.col(key).alias("Group"), pl.col(value).alias("Value")
    )


def _bars(frame: pl.DataFrame, recipe: recipes.Recipe):
    color = (config.graph_colorway() or [ACCENT])[0]
    data = _simple(frame, recipe.group_by, recipes.value_label(recipe)).head(recipe.top)
    chart = (
        alt.Chart(data)
        .mark_bar(color=color)
        .encode(
            y=alt.Y("Group:N", sort="-x", title=None),
            x=alt.X("Value:Q", title=recipes.value_label(recipe)),
            tooltip=["Group", alt.Tooltip("Value:Q", format=",.0f")],
        )
        .properties(width="container", height=max(120, 26 * data.height))
    )
    return mo.ui.altair_chart(chart, chart_selection=False, legend_selection=False)


def _area(frame: pl.DataFrame, recipe: recipes.Recipe):
    color = config.graph_fill_color() or ACCENT
    data = _simple(frame, "Period", recipes.value_label(recipe)).rename(
        {"Group": "Period"}
    )
    chart = (
        alt.Chart(data)
        .mark_area(color=color, opacity=0.5, line={"color": color})
        .encode(
            x=alt.X("Period:T", title=None),
            y=alt.Y("Value:Q", title=recipes.value_label(recipe)),
            tooltip=["Period:T", alt.Tooltip("Value:Q", format=",.0f")],
        )
        .properties(width="container", height=220)
    )
    return mo.ui.altair_chart(chart, chart_selection=False, legend_selection=False)


def _table(frame: pl.DataFrame, recipe: recipes.Recipe):
    html = recipes.styled(frame, recipe.highlight, recipe.highlight_value).as_raw_html()
    note = recipes.highlight_note(recipe.highlight, recipe.highlight_value)
    parts = [
        mo.Html(f'<div style="max-height:460px;overflow:auto">{html}</div>'),
        mo.md(f"<small>{frame.height} rows. {note}</small>"),
    ]
    if config.feature("export_ods"):
        parts.append(_ods_button(frame, recipe))
    return mo.vstack(parts)


def _ods_button(frame: pl.DataFrame, recipe: recipes.Recipe):
    """The table as a spreadsheet (.ods), with the cells put in relief as on the page."""
    name = re.sub(
        r"[^A-Za-z0-9_-]+", "-", f"{recipe.output}-{recipe.measure or 'rows'}"
    )
    return mo.download(
        data=lambda: ods.to_ods(
            recipes.plain(frame),
            recipes.cell_fills(frame, recipe.highlight, recipe.highlight_value),
            bold_fills=recipe.highlight != "heatmap",
        ),
        filename=f"kpi-{name}.ods",
        mimetype="application/vnd.oasis.opendocument.spreadsheet",
        label="Download .ods",
    )


def _card(recipe: recipes.Recipe, frame: pl.LazyFrame):
    card = recipes.card(recipe, frame)
    change = card.change
    stat = mo.stat(
        value=_number(card.value),
        label=recipes.title(recipe),
        caption=None if change is None else f"{change:+.1f} % vs the previous period",
        direction=(
            None if change is None else ("increase" if change >= 0 else "decrease")
        ),
        bordered=True,
    )
    alert = _alert(recipe, card.value)
    return mo.vstack([stat, alert]) if alert else stat


def _alert(recipe: recipes.Recipe, value):
    """The line under a card that is beyond its alert threshold (the alerts feature)."""
    limit = recipe.highlight_value
    if value is None:
        return None
    if recipe.highlight == "alert_above" and value > limit:
        return mo.callout(f"Above the alert threshold ({limit:g}).", kind="danger")
    if recipe.highlight == "alert_below" and value < limit:
        return mo.callout(f"Below the alert threshold ({limit:g}).", kind="danger")
    return None


def render(recipe: recipes.Recipe, frame: pl.LazyFrame):
    """The KPI of a recipe on a table, or what is missing / what went wrong."""
    problem = recipes.missing(recipe)
    if problem:
        return mo.callout(problem, kind="info")
    window = recipes.window_of(recipe)
    code = mo.accordion(
        {
            "The polars behind it": mo.md(
                f"```python\n{recipes.polars_code(recipe, window)}\n```"
            )
        }
    )
    try:
        if recipe.output == "card":
            return mo.vstack([_card(recipe, frame), code])
        result = recipes.compute(recipe, frame, window)
    except Exception as err:
        return mo.vstack(
            [
                mo.callout(
                    mo.md(f"**It could not be computed.** {err}"), kind="danger"
                ),
                code,
            ]
        )
    parts = [mo.md(f"### {recipes.title(recipe)}")]
    concentrated = recipes.concentration(recipe, frame)  # None unless the feature is on
    if concentrated:
        parts.append(mo.callout(concentrated, kind="neutral"))
    if recipe.output == "trend":
        parts.append(_area(result, recipe))
    elif recipe.output == "ranking":
        parts.append(_bars(result, recipe))
    parts += [_table(result, recipe), code]
    return mo.vstack(parts)
