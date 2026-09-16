"""Exec the KPI tile definitions stored in `kt.dataset.line` records.

Framework agnostic: returns plain objects (`TileResult`), no UI
dependency, usable from any dashboarding framework (shiny, nicegui...).
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import plotly.express as px
import plotly.graph_objs as go
import polars as pl

from kpiten_core import serial, sandbox
from kpiten_core.month import apply_monthly, is_date

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
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.df is None and self.figure is None and self.value is None


def filter_df(df, predicates):
    """Apply the predicates whose columns exist on the df."""
    applicable = [
        p for p in predicates if all(col in df.columns for col in p.meta.root_names())
    ]
    if applicable:
        return df.filter(applicable)
    return df


def _resolve_table(store, table: str) -> pl.DataFrame:
    """Retrieve a df from the store (mapping table name -> pl.DataFrame)."""
    if table in store:
        return store[table]
    raise TileError(f"table '{table}' is not stored (available : {sorted(store)})")


def exec_tile(
    line: dict,
    table: str,
    store: dict[str, pl.DataFrame],
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
            value = card_case(line["content"], table, store, full_predicates)
            return TileResult("card", label, value=value)
        if kind == "graph":
            fig = graph_case(line["content"], table, store, full_predicates)
            return TileResult("graph", label, figure=fig)
        if kind == "pivot":
            df = pivot_case(line["content"], table, store, full_predicates)
            return TileResult("pivot", label, df=df)
        if kind == "union":
            df = union_case(line, store, full_predicates)
            return TileResult("union", label, df=df)
        if kind == "data":
            df = dataframe_case(line["content"], table, store, full_predicates)
            return TileResult("data", label, df=df)
    except TileError:
        raise
    except Exception as err:
        logger.error("Could not load tile %s", label, exc_info=True)
        raise TileError(f"Error tile '{label}' ({kind}) : {err}") from err
    raise TileError(f"unknown kind '{kind}' for tile '{label}'")


def card_case(content, table, store, full_predicates):
    card_json = serial.loads(content)
    # `from` is optional : defaults to the tile's dataset model (`table`)
    used_df = _resolve_table(store, card_json.get("from", table))
    used_df = filter_df(used_df, full_predicates)
    df = used_df.sql(f'SELECT count(id) FROM self WHERE {card_json.get("where")}')
    if df.is_empty():
        raise TileError(f"Card returned no row")
    return df.to_dict()["id"][0]


def graph_case(content, table, store, full_predicates):
    graph_json = serial.loads(content)
    cx = graph_json["x"]
    cy = graph_json["y"]
    df = _resolve_table(store, graph_json.get("from", table))

    source = filter_df(df, full_predicates)
    source = _agg(source, cy["name"], cx["name"], cx["aggregation"])
    source = _agg(source, cx["name"], cy["name"], cy["aggregation"])
    # Default order : largest to smallest on the y axis, unless the x axis
    # is temporal (a date keeps its natural chronological order).
    if not is_date(source, cx["name"]):
        source = source.sort(cy["name"], descending=True)

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
    return fig


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


def _resolve_derived_date_columns(df: pl.DataFrame, *names) -> pl.DataFrame:
    """Add derived date columns like `date_order.year` when missing.

    The serialized pivot/graph definitions may reference derived columns
    (`<col>.year`, `<col>.month`, ...).
    """
    exprs = []
    for name in [n for n in names if n]:
        root, _, suffix = name.rpartition(".")
        if (
            not root
            or root not in df.columns
            or not is_date(df, root)
            or suffix not in DERIVED_DT_SUFFIX
            or name in df.columns
        ):
            continue
        fmt = {"year": "%Y", "month": "%b %Y", "week": "%G W%V", "quarter": "%YT%q"}
        exprs.append(pl.col(root).dt.strftime(fmt[suffix]).alias(name))
    return df.with_columns(exprs) if exprs else df


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

    return df.pivot(
        index=index,
        on=column,
        values=measure,
        aggregate_function=aggregation,
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
    df = filter_df(_resolve_table(store, table), full_predicates)
    return sandbox.run(content, df, df_var, out_var)


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
