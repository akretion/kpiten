"""The data of a graph tile : what a front draws, with the library it wants.

The core computes the points of a graph (filtered, aggregated, sorted, bounded : see
`tiles.graph_case`) ; it draws nothing. `kpiten_core.render.plotly` turns a `Chart` into a
plotly figure (the `render` extra) ; another front may draw it its own way.
"""

from dataclasses import dataclass, field

import polars as pl

KINDS = ("bar", "line", "area", "point", "pie")


@dataclass
class Chart:
    kind: str  # bar, line, area, point (a scatter) or pie
    x: str  # the column of `points` on the x axis (a pie : its slices)
    y: str  # ... on the y axis (a pie : the size of the slices)
    points: pl.DataFrame  # one row per bar / point, in the order to draw them
    labels: dict[str, str] = field(default_factory=dict)  # column -> axis title
    temporal: bool = False  # x is a date : a time axis
    series: str | None = None  # a column of `points` : one color per value
    stacked: bool = False  # the series one on the other (bar, area)
    orientation: str = "v"  # "h" : horizontal bars (long labels)
    plotly: dict = field(default_factory=dict)  # {layout, traces} : given to plotly
