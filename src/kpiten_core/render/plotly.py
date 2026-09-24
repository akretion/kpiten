"""A graph tile as a plotly figure, in the colors of `kt.config` or of the theme."""

import logging
import re

import plotly.express as px

from kpiten_core import config as settings
from kpiten_core.charts import Chart

logger = logging.getLogger(__name__)

DRAW = {"bar": px.bar, "line": px.line, "point": px.scatter, "area": px.area}


def figure(chart: Chart):
    """The plotly figure of a graph, with the layout and the colors of `kt.config`.
    The front styles it for its theme, then calls `finish` (the `[plotly]` of the
    tile has the last word)."""
    fig = _draw(chart)
    graph = settings.CONFIG.get("graph") or {}
    layout = {
        **graph.get("layout", {}),
        "autosize": True,
        "margin": dict(l=20, r=20, t=40, b=20),
    }
    fig.update_layout(**layout)
    colorway = graph.get("layout", {}).get("colorway")
    if chart.series:  # a color per series
        _color_series(fig, colorway)
    else:  # a color per bar
        _apply_colorway(fig, colorway)
        _apply_fill_color(fig, graph.get("fill_color"), chart.kind)
    return fig


def _color_series(fig, colorway: list | None) -> None:
    """One color of `colorway` per trace (a series) : plotly express fixes its own
    colors on each trace, the `colorway` of the layout alone would not show."""
    if not colorway:
        return
    for i, trace in enumerate(fig.data):
        color = colorway[i % len(colorway)]
        if trace.type in ("bar", "scatter"):
            trace.marker.color = color
        if trace.type == "scatter":
            trace.line.color = color
            if getattr(trace, "fill", None) or getattr(trace, "stackgroup", None):
                trace.fillcolor = _with_alpha(color, 0.5)


def _draw(chart: Chart):
    """The traces of a graph : its kind, its series, stacked or not, its orientation."""
    if chart.kind == "pie":
        return px.pie(chart.points, names=chart.x, values=chart.y, labels=chart.labels)
    horizontal = chart.orientation == "h" and chart.kind == "bar"
    options = dict(labels=chart.labels, color=chart.series)
    if horizontal:  # the categories on y, the biggest on top
        options.update(x=chart.y, y=chart.x, orientation="h")
    else:
        options.update(x=chart.x, y=chart.y)
    if chart.series:  # sorted : a series keeps its color from one run to the next
        values = chart.points[chart.series].drop_nulls().unique().sort().to_list()
        options["category_orders"] = {chart.series: values}
    if chart.kind == "bar" and chart.series:
        options["barmode"] = "stack" if chart.stacked else "group"
    fig = DRAW.get(chart.kind, px.bar)(chart.points, **options)
    if horizontal:
        fig.update_yaxes(autorange="reversed")
    if chart.kind in ("line", "area") and chart.series and not chart.stacked:
        if chart.kind == "area":  # px.area stacks : each series from zero
            fig.update_traces(stackgroup=None, fill="tozeroy")
    return fig


def finish(fig, chart: Chart) -> None:
    """The `[plotly]` of the tile on its figure, after the styling of the front :
    `layout` to `update_layout`, `traces` to `update_traces`. What plotly refuses is
    left out (logged)."""
    for key, update in (("layout", fig.update_layout), ("traces", fig.update_traces)):
        options = (chart.plotly or {}).get(key)
        if not options:
            continue
        try:
            update(**options)
        except (ValueError, TypeError):
            logger.warning("[plotly.%s] ignored : %s", key, options)


def _apply_colorway(fig, colorway: list | None) -> None:
    """Apply the configured colorway to each bar element.

    px.bar sets a single scalar `marker.color` on the trace, which makes
    plotly color every bar the same and ignore the layout `colorway`. We
    therefore expand the palette per element (cycling) so the configured
    colors actually show up.
    """
    if not colorway:
        return
    for trace in fig.data:
        if trace.type != "bar":
            continue
        x = trace.x if trace.x is not None else (trace.y if trace.y is not None else [])
        n = len(x)
        trace.marker.color = [colorway[i % len(colorway)] for i in range(n)]


def apply_theme_colors(fig, palette: dict) -> None:
    """The colors of the theme on a graph : its colorway on the bars, its first color on
    a filled graph (area). When `kt.config` says the colors come from it, only where it
    sets none."""
    colorway = palette.get("colorway")
    if not colorway:
        return
    themed = settings.colors_from_theme()
    if themed or not settings.graph_colorway():
        fig.update_layout(colorway=colorway, piecolorway=colorway)
        if len(fig.data) == 1:
            _apply_colorway(fig, colorway)
        else:  # series : one color each, from the colorway
            _color_series(fig, colorway)
    if (themed or not settings.graph_fill_color()) and len(fig.data) == 1:
        for trace in fig.data:
            # px.area fills through its stackgroup (`fill` stays None)
            filled = getattr(trace, "fill", None) in ("tozeroy", "tonexty")
            if filled or getattr(trace, "stackgroup", None):
                trace.line.color = colorway[0]
                trace.fillcolor = _with_alpha(colorway[0], 0.5)


def _with_alpha(color: str, alpha: float) -> str:
    """`#33d17a` -> `rgba(51, 209, 122, 0.5)` ; any other notation is kept as it is."""
    match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color.strip())
    if not match:
        return color
    digits = match[1]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _apply_fill_color(fig, color: str | None, kind: str) -> None:
    """The configured color of a filled graph (`area`) : its line, and its fill at
    half opacity. The palette is for bars ; without a color plotly's default stays."""
    if not color or kind != "area":
        return
    for trace in fig.data:
        trace.line.color = color
        trace.fillcolor = _with_alpha(color, 0.5)
