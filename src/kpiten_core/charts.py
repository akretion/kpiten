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
    trend: pl.DataFrame | None = None  # x, y : the linear trend and the points ahead


def linear_trend(points: pl.DataFrame, x: str, y: str, ahead: int = 0):
    """The least squares line through the points of a time axis (one per step, in
    order), prolonged `ahead` steps : a DataFrame (x, y), None under 3 points. A month
    steps by a month ; another step by the last gap between two points."""
    df = points.select(x, pl.col(y).cast(pl.Float64)).drop_nulls().sort(x)
    n = df.height
    if n < 3:
        return None
    xs, ys = df[x].to_list(), df[y].to_list()
    mean_i, mean_y = (n - 1) / 2, sum(ys) / n
    slope = sum((i - mean_i) * (v - mean_y) for i, v in enumerate(ys)) / sum(
        (i - mean_i) ** 2 for i in range(n)
    )
    start = mean_y - slope * mean_i
    monthly = all(getattr(d, "day", None) == 1 for d in xs)

    def later(k: int):  # the point k steps after the last one
        if monthly:
            return pl.Series([xs[-1]]).dt.offset_by(f"{k}mo").item()
        return xs[-1] + k * (xs[-1] - xs[-2])

    dates = xs + [later(k) for k in range(1, ahead + 1)]
    return pl.DataFrame(
        {x: dates, y: [start + slope * i for i in range(len(dates))]},
        schema={x: df.schema[x], y: pl.Float64},
    )
