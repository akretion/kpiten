"""Exec the KPI tile definitions stored in `kt.dataset.line` records.

Framework agnostic: returns plain objects (`TileResult`), no UI
dependency, usable from any dashboarding framework (shiny, nicegui...).
"""

import datetime
import decimal
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import plotly.express as px
import plotly.graph_objs as go
import polars as pl

from kpiten_core import env, serial, sandbox
from kpiten_core.month import apply_monthly, is_date
from kpiten_core.validate import CARD_AGGREGATIONS, DERIVE_RE

logger = logging.getLogger(__name__)


class TileError(Exception):
    """Wrap any kind of tile computation error with a nice message."""


@dataclass
class TileResult:
    kind: str
    label: str | None
    df: pl.DataFrame | None = None
    figure: go.Figure | None = None
    value: Any = None
    display: str | None = None  # formatted `value` (cards : unit, decimals)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.df is None and self.figure is None and self.value is None

    @property
    def note(self) -> str | None:
        """Why the tile shows less than the whole data (None when complete)."""
        return self.meta.get("note")

    @property
    def text(self) -> str:
        """What a card shows : the formatted value, else the raw value."""
        return self.display if self.display is not None else str(self.value)


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _collect(lf: pl.LazyFrame, ordered: bool = False) -> pl.DataFrame:
    """Run a lazy query. Streaming keeps the memory bounded when it has to
    go through a big table (the result itself is always small here).

    The streaming engine does not keep the order of a `group_by`, so a query
    whose row / column order shows in the tile (pivot) runs with
    `ordered=True` on the in-memory engine : it only reads the columns it
    needs, and the order is then the same from one run to the next.
    """
    return lf.collect() if ordered else lf.collect(engine="streaming")


def cap_rows(
    frame: pl.DataFrame | pl.LazyFrame,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Keep the first `env.tile_max_rows` rows of a table tile.

    Takes a DataFrame or a LazyFrame (a union of two big tables is only ever
    read for its first rows). Returns (df, meta) ; `meta["note"]` says what
    was cut off. The front never gets more rows than it can render.
    """
    if isinstance(frame, pl.LazyFrame):
        total = _collect(frame.select(pl.len())).item()
        if total <= env.tile_max_rows:
            return _collect(frame), {}
        df = _collect(frame.head(env.tile_max_rows))
    else:
        total = frame.height
        if total <= env.tile_max_rows:
            return frame, {}
        df = frame.head(env.tile_max_rows)
    return df, {
        "total_rows": total,
        "note": f"First {_fmt_int(env.tile_max_rows)} of {_fmt_int(total)} rows",
    }


def filter_df(df, predicates):
    """Apply the predicates whose columns exist on the df (DataFrame or
    LazyFrame, the same kind comes back)."""
    columns = set(df.collect_schema().names())
    applicable = [
        p for p in predicates if all(col in columns for col in p.meta.root_names())
    ]
    if applicable:
        return df.filter(applicable)
    return df


def _resolve_table(store, table: str) -> pl.LazyFrame:
    """Retrieve a table from the store (mapping table name -> DataFrame or
    LazyFrame) as a LazyFrame : tiles build one query and collect only its
    (small) result, so the table itself is never fully loaded."""
    if table in store:
        return store[table].lazy()
    raise TileError(f"table '{table}' is not stored (available : {sorted(store)})")


def exec_tile(
    line: dict,
    table: str,
    store: dict[str, pl.DataFrame | pl.LazyFrame],
    full_predicates: list[pl.Expr],
) -> TileResult:
    """Exec one tile from a kt.dataset.line record dict.

    `line` structure is what `Backend.get_panel_lines` yields.
    `table` is the technical model name of the tile's dataset ; its df
    is looked up in `store`.
    """
    kind = line.get("kind")
    label = line.get("name") or kind
    try:
        if kind == "card":
            value, display = card_case(line["content"], table, store, full_predicates)
            return TileResult("card", label, value=value, display=display)
        if kind == "graph":
            fig, meta = graph_case(line["content"], table, store, full_predicates)
            return TileResult("graph", label, figure=fig, meta=meta)
        if kind == "pivot":
            df = pivot_case(line["content"], table, store, full_predicates)
            df, meta = cap_rows(df)
            return TileResult("pivot", label, df=df, meta=meta)
        if kind == "union":
            df = union_case(line, store, full_predicates)
            df, meta = cap_rows(df)
            return TileResult("union", label, df=df, meta=meta)
        if kind == "data":
            df = dataframe_case(line["content"], table, store, full_predicates)
            df, meta = cap_rows(df)
            return TileResult("data", label, df=df, meta=meta)
    except TileError:
        raise
    except Exception as err:
        logger.error("Could not load tile %s", label, exc_info=True)
        raise TileError(f"Error tile '{label}' ({kind}) : {err}") from err
    raise TileError(f"unknown kind '{kind}' for tile '{label}'")


TODAY_RE = re.compile(r"\{today(?:-(\d+))?\}")


def expand_today(where: str, today: datetime.date | None = None) -> str:
    """Replace `{today}` / `{today-N}` by an ISO date (N days back), so that a
    `where` can express « late » (`date_planned < '{today}'`) or « last 7
    days » (`date_approve >= '{today-7}'`)."""
    today = today or datetime.date.today()

    def day(match):
        return (today - datetime.timedelta(days=int(match.group(1) or 0))).isoformat()

    return TODAY_RE.sub(day, where)


def derive_columns(df, derive: dict[str, str]):
    """Add derived columns : `{"days_to_order": "date_approve - create_date"}`
    gives the whole days between two date columns (null if one is null)."""
    exprs = []
    for name, expression in derive.items():
        match = DERIVE_RE.match(expression)
        if not match:
            raise TileError(f"derive '{name}' : expected '<date> - <date>'")
        end, start = match.groups()
        for column in (end, start):
            if column not in df.collect_schema():
                raise TileError(f"derive '{name}' : unknown column '{column}'")
        exprs.append((pl.col(end) - pl.col(start)).dt.total_days().alias(name))
    return df.with_columns(exprs) if exprs else df


def format_card_value(value, aggregation: str, card: dict) -> str:
    """Card text : thousands separated by a narrow space, `decimals`
    (default 0 for count/sum, 1 otherwise) and an optional `unit`."""
    if value is None:
        return "–"
    decimals = card.get("decimals", 0 if aggregation in ("count", "sum") else 1)
    text = f"{value:,.{decimals}f}".replace(",", " ")
    unit = card.get("unit")
    return f"{text} {unit}" if unit else text


def _without_period(df: pl.DataFrame, predicates):
    """The predicates that are not on a date column : the panel dimension
    filters (vendor...) stay, the Period filter goes. It also excludes the
    future, which « waiting » or « to send » kpis must count."""
    return [
        p
        for p in predicates
        if not any(is_date(df, name) for name in p.meta.root_names())
    ]


def card_case(content, table, store, full_predicates):
    """One number : `aggregation` (count by default) of `measure` over the
    rows matching `where` (SQL, optional). Returns `(value, display)`."""
    card_json = serial.loads(content)
    aggregation = card_json.get("aggregation", "count")
    if aggregation not in CARD_AGGREGATIONS:
        raise TileError(f"unknown card aggregation '{aggregation}'")
    measure = card_json.get("measure")
    # `from` is optional : defaults to the tile's dataset model (`table`)
    df = _resolve_table(store, card_json.get("from", table))
    if card_json.get("ignore_period"):
        full_predicates = _without_period(df, full_predicates)
    df = filter_df(df, full_predicates)
    df = derive_columns(df, card_json.get("derive") or {})
    if card_json.get("where"):
        df = df.sql(f"SELECT * FROM self WHERE {expand_today(card_json['where'])}")

    if aggregation == "count":
        expr = pl.col(measure).count() if measure else pl.len()
    elif measure not in df.collect_schema():
        raise TileError(f"card '{aggregation}' needs a `measure` column")
    else:
        expr = getattr(pl.col(measure), aggregation)()
    value = _collect(df.select(expr)).item()
    if isinstance(value, decimal.Decimal):
        value = float(value)
    return value, format_card_value(value, aggregation, card_json)


def _bound_dates(source: pl.LazyFrame, column: str) -> tuple[pl.LazyFrame, str | None]:
    """Group a date axis by month when it has more days than `tile_max_points`
    (before aggregating, so a mean stays a real mean). Returns (df, note)."""
    distinct = _collect(source.select(pl.col(column).n_unique())).item()
    if distinct <= env.tile_max_points:
        return source, None
    return apply_monthly(source, column), "Grouped by month"


def _bound_categories(
    source: pl.DataFrame, x: str, y: str, aggregation: str
) -> tuple[pl.DataFrame, str | None]:
    """Keep the `tile_max_categories` biggest bars of a sorted (desc) graph
    source ; the rest is folded in an "Others" bar when that is meaningful
    (sum / count of a text axis). Returns (df, note)."""
    total = source.height
    limit = env.tile_max_categories
    if total <= limit:
        return source, None
    top, rest = source.head(limit), source.tail(total - limit)
    note = f"Top {_fmt_int(limit)} of {_fmt_int(total)}"
    if aggregation in ("sum", "count") and source.schema[x] == pl.String:
        others = pl.DataFrame(
            {x: ["Others"], y: [rest[y].sum()]},
            schema={x: source.schema[x], y: source.schema[y]},
        )
        top = pl.concat([top, others])
        note += " (rest in Others)"
    return top, note


def graph_case(content, table, store, full_predicates):
    """Build the plotly figure of a graph tile. Returns `(figure, meta)` ;
    `meta["note"]` says how the data was reduced to stay drawable."""
    graph_json = serial.loads(content)
    cx = graph_json["x"]
    cy = graph_json["y"]
    df = _resolve_table(store, graph_json.get("from", table))
    notes = []

    source = filter_df(df, full_predicates)
    temporal = is_date(source, cx["name"])
    if temporal:
        source, note = _bound_dates(source, cx["name"])
        notes.append(note)
    source = _agg(source, cy["name"], cx["name"], cx["aggregation"])
    source = _agg(source, cx["name"], cy["name"], cy["aggregation"])
    source = _collect(source)  # one row per bar / point from here on
    # Default order : largest to smallest on the y axis, unless the x axis
    # is temporal (a date keeps its natural chronological order).
    if temporal:
        source = source.sort(cx["name"])
        if source.height > env.tile_max_points:  # still too many : latest ones
            source = source.tail(env.tile_max_points)
            notes.append(f"Latest {_fmt_int(env.tile_max_points)} points")
    else:
        # ties on y are ordered by x : the bars do not swap between two runs
        source = source.sort([cy["name"], cx["name"]], descending=[True, False])
        source, note = _bound_categories(
            source, cx["name"], cy["name"], cy["aggregation"]
        )
        notes.append(note)

    labels = {
        col: col.replace("_", " ").capitalize() for col in (cx["name"], cy["name"])
    }
    common_args = dict(x=cx["name"], y=cy["name"], labels=labels)
    chart = {"bar": px.bar, "point": px.scatter, "area": px.area}
    fig = chart.get(graph_json["graph_type"], px.bar)(source, **common_args)
    layout = dict(
        autosize=True,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    if CHART_CONFIG.get("graph"):
        layout = {**CHART_CONFIG["graph"].get("layout", {}), **layout}
    fig.update_layout(**layout)
    _apply_colorway(
        fig, (CHART_CONFIG.get("graph") or {}).get("layout", {}).get("colorway")
    )
    notes = [n for n in notes if n]
    return fig, ({"note": ". ".join(notes)} if notes else {})


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


# Chart styling defaults, set by the UI apps from their odoo config
# (single `kt.config` record : {"graph": {"layout": {...}}})
CHART_CONFIG: dict = {}


def set_chart_config(config: dict):
    """Apply the odoo-side chart defaults (see kt.get_chart_config)."""
    CHART_CONFIG.clear()
    CHART_CONFIG.update(config or {})


DERIVED_DT_SUFFIX = {"year", "quarter", "month", "week", "day"}


def _resolve_derived_date_columns(df, *names):
    """Add derived date columns like `date_order.year` when missing.

    The serialized pivot/graph definitions may reference derived columns
    (`<col>.year`, `<col>.month`, ...).
    """
    exprs = []
    columns = df.collect_schema()
    for name in [n for n in names if n]:
        root, _, suffix = name.rpartition(".")
        if (
            not root
            or root not in columns
            or not is_date(df, root)
            or suffix not in DERIVED_DT_SUFFIX
            or name in columns
        ):
            continue
        fmt = {"year": "%Y", "month": "%b %Y", "week": "%G W%V", "quarter": "%YT%q"}
        exprs.append(pl.col(root).dt.strftime(fmt[suffix]).alias(name))
    return df.with_columns(exprs) if exprs else df


PIVOT_AGGREGATIONS = {"sum": pl.Expr.sum, "mean": pl.Expr.mean, "count": pl.Expr.len}


def pivot_case(content, table, store, full_predicates):
    pivot_json = serial.loads(content)
    index = pivot_json["index"]
    column = pivot_json["column"]
    measure = pivot_json["measure"]
    aggregation = pivot_json.get("aggregation", "sum")
    monthly = pivot_json.get("monthly", False)

    df = _resolve_table(store, pivot_json.get("from", table))
    df = filter_df(df, full_predicates)
    df = _resolve_derived_date_columns(df, index, column)
    if monthly and column and is_date(df, column):
        df = apply_monthly(df, column)
    elif monthly and index and is_date(df, index):
        df = apply_monthly(df, index)

    distinct = _collect(df.select(pl.col(column).n_unique())).item() if column else 0
    if distinct > env.tile_max_pivot_columns:
        raise TileError(
            f"pivot column '{column}' has {_fmt_int(distinct)} distinct values "
            f"(max {env.tile_max_pivot_columns}) : pick a coarser column "
            "(e.g. `.year` / `.month`) or filter the period"
        )
    if aggregation not in PIVOT_AGGREGATIONS:
        raise TileError(f"pivot aggregation '{aggregation}' is not supported")
    # Aggregate lazily to one row per (index, column) cell : only that small
    # frame is collected and pivoted (`pivot` needs an eager DataFrame). Each
    # cell is now a single value, "first" just moves it.
    cells = _collect(
        df.group_by([index, column], maintain_order=True).agg(
            PIVOT_AGGREGATIONS[aggregation](pl.col(measure)).alias(measure)
        ),
        ordered=True,
    )
    return cells.pivot(
        index=index, on=column, values=measure, aggregate_function="first"
    )


def union_case(transform: dict[str, Any], store, full_predicates):
    union_json = serial.loads(transform["content"])
    union_model = union_json["union_model"]
    mapping = union_json["mapping"]
    base_model = next(m for m in mapping if m != union_model)
    dfs = [
        filter_df(_resolve_table(store, m), full_predicates)
        .select(mapping[m].keys())
        .rename(mapping[m])
        for m in (base_model, union_model)
    ]
    return pl.concat(dfs, how="vertical_relaxed")


def dataframe_case(content, table, store, full_predicates):
    """Run the `data` kind definition through the sandbox.

    The definition's first line `d_next = d ` holds the input/output vars.
    """
    first_line = content.partition("\n")[0]
    out_var = first_line.split(" ")[0]
    df_var = first_line.split(" ")[2]
    lazy = filter_df(_resolve_table(store, table), full_predicates)
    try:
        return sandbox.run(content, lazy, df_var, out_var)
    except AttributeError:
        # the snippet uses an eager-only method (pivot, transpose, describe...) :
        # give it the filtered rows in memory
        return sandbox.run(content, _collect(lazy), df_var, out_var)


def _agg(source: pl.DataFrame, group_col, agg_col, agg_fn):
    if group_col == agg_col:
        return source
    if agg_fn == "sum":
        return source.group_by(group_col).agg(pl.col(agg_col).sum())
    if agg_fn == "count":
        return source.group_by(group_col).agg(pl.col(agg_col).count())
    if agg_fn == "mean":
        return source.group_by(group_col).agg(pl.col(agg_col).mean())
    return source
