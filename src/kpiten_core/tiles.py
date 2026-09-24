"""Exec the KPI tile definitions stored in `kt.dataset.line` records.

Framework agnostic: returns plain objects (`TileResult`), no UI
dependency, usable from any dashboarding framework (shiny, nicegui...).
"""

import datetime
import functools
import decimal
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from kpiten_core import config as settings
from kpiten_core.charts import KINDS, Chart
from kpiten_core import env, i18n, labels, links, numfmt, serial, sandbox, spec, sqltile
from kpiten_core.month import apply_monthly, is_date
from kpiten_core.spec import CARD_AGGREGATIONS, DATE_DIFF_RE as DERIVE_RE

logger = logging.getLogger(__name__)


class TileError(Exception):
    """Wrap any kind of tile computation error with a nice message."""


@dataclass
class TileResult:
    kind: str
    label: str | None
    df: pl.DataFrame | None = None
    chart: Chart | None = None  # a graph : its data, drawn by the front
    value: Any = None
    display: str | None = None  # formatted `value` (cards : unit, decimals)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.df is None and self.chart is None and self.value is None

    @functools.cached_property
    def figure(self):
        """The plotly figure of a graph (`render.plotly`, the `render` extra) : built at
        the first call, the same one afterwards (a front may restyle it)."""
        if self.chart is None:
            return None
        from kpiten_core.render.plotly import figure

        return figure(self.chart)

    @property
    def note(self) -> str | None:
        """Why the tile shows less than the whole data (None when complete)."""
        return self.note_in(i18n.english)

    def note_in(self, tr) -> str | None:
        """The note in the language of `tr` (`kpiten_core.i18n.translator`) : the
        notes are `(text, values)` messages in `meta["notes"]`."""
        notes = [tr(text, **values) for text, values in self.meta.get("notes", [])]
        return ". ".join(notes) or None

    @property
    def subtitle(self) -> str | None:
        """A line under a card's value (`best` cards : the units sold)."""
        return self.meta.get("subtitle")

    @property
    def keys(self) -> list[dict[str, Any]] | None:
        """One dict per row of a `data` tile : its hidden `__x` columns (see
        `split_keys`), what a click on the row hands to the tile's drill-down."""
        return self.meta.get("keys")

    @property
    def comparison(self) -> dict[str, Any] | None:
        """How a card compares with the previous period (see `card_comparison`)."""
        return self.meta.get("comparison")

    @property
    def text(self) -> str:
        """What a card shows : the formatted value, else the raw value."""
        return self.display if self.display is not None else str(self.value)


def records_link(backend, model: str, result: TileResult) -> dict | None:
    """The link that opens, in Odoo, the records a `data` tile lists : the same list, with
    the rights of whoever opens it. A tile lists records when its rows carry the hidden
    key `__id` (the id of a record of `model`). None when the feature is off in `kt.config`,
    when the rows are not records, or when Odoo has no action for the model."""
    if not settings.feature("open_in_odoo") or not result.keys:
        return None
    ids = [key.get("id") for key in result.keys]
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return None
    try:
        action = backend.get_records_action_id(model)
    except Exception:
        logger.exception("no records action for %s", model)
        return None
    url, count = links.records_url(links.get_odoo_url(), action, ids)
    return {"url": url, "count": count, "total": len(ids)}


def _fmt_int(n: int) -> str:
    return numfmt.format_number(n)


def rows_note(shown: int, total: int) -> tuple[str, dict]:
    """The note of a table cut off at `shown` rows (a message : `TileResult.note_in`)."""
    return (
        "First {rows} of {total} rows",
        {"rows": _fmt_int(shown), "total": _fmt_int(total)},
    )


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
    read for its first rows). Returns (df, meta) ; `meta["notes"]` says what
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
        "notes": [rows_note(env.tile_max_rows, total)],
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
    previous_predicates: list[pl.Expr] | None = None,
    previous_label: str | None = None,
    field_labels: labels.FieldLabels | None = None,
) -> TileResult:
    """Exec one tile from a kt.dataset.line record dict.

    `line` structure is what `Backend.get_panel_lines` yields.
    `table` is the technical model name of the tile's dataset ; its df
    is looked up in `store`. A card with `compare = true` also gets its value
    for the period before (`previous_predicates`, see
    `filters.make_previous_predicates`) as `TileResult.comparison`.
    `field_labels` gives the labels of the fields of a model in the language of the
    user (`labels.field_labels_of`) : the names shown by default.
    """
    kind = line.get("kind")
    label = line.get("name") or kind
    try:
        if kind == "card":
            value, display, subtitle = card_value(
                line["content"], table, store, full_predicates
            )
            comparison = card_comparison(
                line["content"],
                table,
                store,
                value,
                previous_predicates,
                previous_label,
            )
            meta = {"comparison": comparison} if comparison else {}
            if subtitle:
                meta["subtitle"] = subtitle
            return TileResult("card", label, value=value, display=display, meta=meta)
        if kind == "graph":
            chart, meta = graph_case(
                line["content"], table, store, full_predicates, field_labels
            )
            return TileResult("graph", label, chart=chart, meta=meta)
        if kind == "pivot":
            df, drawing = pivot_case(
                line["content"], table, store, full_predicates, field_labels
            )
            df, meta = cap_rows(df)
            if drawing:
                meta["table"] = drawing
            return TileResult("pivot", label, df=df, meta=meta)
        if kind == "union":
            df = union_case(line, store, full_predicates)
            df, meta = cap_rows(df)
            return TileResult("union", label, df=df, meta=meta)
        if kind == "data":
            df = dataframe_case(line["content"], table, store, full_predicates)
            df, meta = cap_rows(df)
            df, keys = split_keys(df)
            if keys:
                meta["keys"] = keys
            df, drawing = _data_display(line, df, table, field_labels)
            if drawing:
                meta["table"] = drawing
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
    (default 0) and an optional `unit` (`unit = "currency"`
    is the symbol of the company currency, before or after the number as Odoo does)."""
    if value is None:
        return "–"
    decimals = card.get("decimals", 0)
    text = numfmt.format_number(value, decimals)
    unit = card.get("unit")
    if unit == "currency":  # the currency of the company (kt.config)
        return numfmt.with_currency(text)
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
    value, display, _ = card_value(content, table, store, full_predicates)
    return value, display


def _best_case(card_json, df):
    """The `by` card : the name of the group (`by` column) with the biggest
    sum of `measure`, and under it the sum of `[detail] measure` for that group
    (its `label` after it). Returns `(name, display, subtitle)`."""
    detail_json = card_json.get("detail") or {}
    best, measure, detail = (
        card_json["by"],
        card_json.get("measure"),
        detail_json.get("measure"),
    )
    schema = df.collect_schema()
    for column in (best, measure, detail):
        if column and column not in schema:
            raise TileError(f"card 'by' : unknown column '{column}'")
    aggregates = [pl.col(measure).sum().alias("__rank")]
    if detail:
        aggregates.append(pl.col(detail).sum().alias("__detail"))
    top = _collect(
        df.filter(pl.col(best).is_not_null())
        .group_by(best)
        .agg(aggregates)
        .sort(["__rank", best], descending=[True, False])
        .head(1)
    )
    if top.height == 0:
        return None, "–", None
    name = top[best][0]
    subtitle = None
    if detail:
        units = numfmt.format_number(float(top["__detail"][0]))
        subtitle = f"{units} {detail_json.get('label', '')}".strip()
    return name, str(name), subtitle


def card_value(content, table, store, full_predicates):
    """A card's `(value, display, subtitle)` : one number (see `card_case`), or
    with `by` the name of the best group and a line under it."""
    card_json = spec.load(content, "card")
    aggregation = card_json.get("aggregation", "count")
    if aggregation not in CARD_AGGREGATIONS:
        raise TileError(f"unknown card aggregation '{aggregation}'")
    measure = card_json.get("measure")
    # `from` is optional : defaults to the tile's dataset model (`table`)
    df = _resolve_table(store, card_json.get("from", table))
    if card_json.get("ignore_period"):
        full_predicates = _without_period(df, full_predicates)
    df = filter_df(df, full_predicates)
    df = derive_columns(df, card_json.get("computed") or {})
    if card_json.get("where"):
        where = sqltile.check_where(expand_today(card_json["where"]))
        df = df.sql(f"SELECT * FROM self WHERE {where}")

    if card_json.get("by"):
        return _best_case(card_json, df)

    if aggregation == "count":
        expr = pl.col(measure).count() if measure else pl.len()
    elif measure not in df.collect_schema():
        raise TileError(f"card '{aggregation}' needs a `measure` column")
    else:
        expr = getattr(pl.col(measure), aggregation)()
    value = _collect(df.select(expr)).item()
    if isinstance(value, decimal.Decimal):
        value = float(value)
    return value, format_card_value(value, aggregation, card_json), None


def _bound_dates(source: pl.LazyFrame, column: str) -> tuple[pl.LazyFrame, str | None]:
    """Group a date axis by month when it has more days than `tile_max_points`
    (before aggregating, so a mean stays a real mean). Returns (df, note)."""
    distinct = _collect(source.select(pl.col(column).n_unique())).item()
    if distinct <= env.tile_max_points:
        return source, None
    return apply_monthly(source, column), ("Grouped by month", {})


def _bound_categories(
    source: pl.DataFrame,
    x: str,
    y: str,
    aggregation: str,
    others: bool = False,
    limit: int | None = None,
) -> tuple[pl.DataFrame, str | None]:
    """Keep the `tile_max_categories` biggest bars of a sorted (desc) graph
    source. With `others` the rest is folded in one more bar, when that is
    meaningful (sum / count of a text axis) : useful for a share of the total,
    harmful for a ranking, where that bar (all the small ones together) is by
    far the biggest and flattens the others. Returns (df, note)."""
    total = source.height
    limit = limit or env.tile_max_categories
    if total <= limit:
        return source, None
    top, rest = source.head(limit), source.tail(total - limit)
    note = "Top {limit} of {total}"
    if others and aggregation in ("sum", "count") and source.schema[x] == pl.String:
        folded = pl.DataFrame(
            {x: ["Others"], y: [rest[y].sum()]},
            schema={x: source.schema[x], y: source.schema[y]},
        )
        top = pl.concat([top, folded])
        note += " (rest in Others)"
    return top, (note, {"limit": _fmt_int(limit), "total": _fmt_int(total)})


def card_comparison(
    content, table, store, value, previous_predicates, previous_label=None
) -> dict | None:
    """The card against the period before, like the baseline of an Odoo scorecard.

    Only for a card with `compare` (`true`, or `[compare]`), a period to go back from and no
    `ignore_period`, and unless `kt.config` turns the comparison off
    (`comparison_enabled`). Returns `{direction, tone, text, description, previous, period}` :
    `direction` up / down / neutral, `tone` good / bad / neutral (the color : up is
    good unless the card says `[compare] good = "down"`), `text` the change as a percentage of the
    previous value (`|value - previous| / previous`, `n/a` when that is 0),
    `previous` the previous value as the card shows it.
    """
    card_json = spec.load(content, "card")
    if (
        not comparison_enabled()
        or not card_json.get("compare")
        or card_json.get("ignore_period")
        or previous_predicates is None
        or not isinstance(value, (int, float))
    ):
        return None
    previous, previous_display = card_case(content, table, store, previous_predicates)
    if previous is None:
        return None
    change = value - previous
    direction = "up" if change > 0 else "down" if change < 0 else "neutral"
    if change == 0:
        text = "0.0%"
    elif previous == 0:
        text = "n/a"
    else:
        text = f"{abs(change) / abs(previous) * 100:.1f}%"
    compare = card_json["compare"]
    good = compare.get("good", "up") if isinstance(compare, dict) else "up"
    tone = (
        "neutral" if direction == "neutral" else "good" if direction == good else "bad"
    )
    return {
        "direction": direction,
        "tone": tone,
        "text": text,
        "description": "since last period",
        "previous": previous_display,
        "previous_value": previous,
        "period": previous_label,
    }


def _fields(graph_or_pivot: dict, table: str, field_labels) -> dict[str, str]:
    """The labels of the fields of the table the tile reads (none without them)."""
    if field_labels is None:
        return {}
    return field_labels(graph_or_pivot.get("from", table))


def graph_case(content, table, store, full_predicates, field_labels=None):
    """The data of a graph tile (`charts.Chart` : drawn by the front). Returns
    `(chart, meta)` ;
    `meta["notes"]` says how the data was reduced to stay drawable.

    `by` is the x axis, `measure` aggregated by `aggregation` the y axis. Optional
    keys : `where` (SQL over the rows, like a card's), `grain = "month"` (a date
    x axis is grouped by month), `others` (the bars past the limit are
    folded in an "Others" bar instead of being dropped), `limit` (the bars kept),
    `series` (one color per value of a column), `stacked`, `orientation` and
    `[plotly]` (given to plotly by `render.plotly.finish`).
    """
    graph_json = spec.load(content, "graph")
    cx = {"name": graph_json["by"], "aggregation": "none"}
    cy = {
        "name": graph_json["measure"],
        "aggregation": graph_json.get("aggregation", "sum"),
    }
    df = _resolve_table(store, graph_json.get("from", table))
    notes = []

    source = filter_df(df, full_predicates)
    source = derive_columns(source, graph_json.get("computed") or {})
    if graph_json.get("where"):
        where = sqltile.check_where(expand_today(graph_json["where"]))
        source = source.sql(f"SELECT * FROM self WHERE {where}")
    temporal = is_date(source, cx["name"])
    if temporal and graph_json.get("grain") == "month":
        source = apply_monthly(source, cx["name"])
    if temporal:
        source, note = _bound_dates(source, cx["name"])
        notes.append(note)
    series = graph_json.get("series")
    if series and series not in source.collect_schema():
        raise TileError(f"graph 'series' : unknown column '{series}'")
    limit = graph_json.get("limit") or env.tile_max_categories
    if series:  # one row per (x, series) : the bars of a group, the lines...
        chart_source, note = _series_points(
            source, cx["name"], cy["name"], cy["aggregation"], series, temporal, limit
        )
        notes.append(note)
        return _chart(
            graph_json, table, field_labels, chart_source, cx, cy, temporal, notes
        )
    source = _agg(source, cy["name"], cx["name"], cx["aggregation"])
    source = _agg(source, cx["name"], cy["name"], cy["aggregation"])
    source = _collect(source)  # one row per bar / point from here on
    # Default order : largest to smallest on the y axis, unless the x axis
    # is temporal (a date keeps its natural chronological order).
    if temporal:
        source = source.sort(cx["name"])
        if source.height > env.tile_max_points:  # still too many : latest ones
            source = source.tail(env.tile_max_points)
            notes.append(
                ("Latest {points} points", {"points": _fmt_int(env.tile_max_points)})
            )
    else:
        # ties on y are ordered by x : the bars do not swap between two runs
        source = source.sort([cy["name"], cx["name"]], descending=[True, False])
        source, note = _bound_categories(
            source,
            cx["name"],
            cy["name"],
            cy["aggregation"],
            bool(graph_json.get("others")),
            limit,
        )
        notes.append(note)
    return _chart(graph_json, table, field_labels, source, cx, cy, temporal, notes)


def _chart(graph_json, table, field_labels, points, cx, cy, temporal, notes):
    """The `Chart` of a graph and its meta (the notes)."""
    series = graph_json.get("series")
    fields = _fields(graph_json, table, field_labels)
    shown = {
        col: labels.column_label(col, graph_json.get("labels"), fields)
        for col in (cx["name"], cy["name"], series)
        if col
    }
    kind = graph_json.get("type", "bar")
    chart = Chart(
        kind if kind in KINDS else "bar",
        cx["name"],
        cy["name"],
        points,
        shown,
        temporal,
        series=series,
        stacked=bool(graph_json.get("stacked")),
        orientation=graph_json.get("orientation", "v"),
        plotly=graph_json.get("plotly") or {},
    )
    notes = [n for n in notes if n]
    return chart, ({"notes": notes} if notes else {})


def _series_points(source, x, y, aggregation, series, temporal, limit):
    """One row per (x, series value), `aggregation` of y. A date x keeps its order ;
    else the x values are ranked by their total over the series, the `limit` biggest
    kept. Returns (points, note)."""
    # the same aggregations as `_agg` (count : the values, not the rows)
    agg = {"sum": pl.Expr.sum, "mean": pl.Expr.mean, "count": pl.Expr.count}[
        aggregation
    ]
    points = _collect(
        source.filter(pl.col(x).is_not_null())
        .group_by([x, series])
        .agg(agg(pl.col(y)).alias(y))
    )
    if temporal:
        return points.sort([x, series]), None
    ranks = (
        points.group_by(x)
        .agg(pl.col(y).sum().alias("__total"))
        .sort(["__total", x], descending=[True, False])
        .with_row_index("__rank")
    )
    total = ranks.height
    ranks = ranks.head(limit)
    points = (
        points.join(ranks.select([x, "__rank"]), on=x)
        .sort(["__rank", series])
        .drop("__rank")
    )
    if total <= limit:
        return points, None
    note = (
        "Top {limit} of {total}",
        {"limit": _fmt_int(limit), "total": _fmt_int(total)},
    )
    return points, note


# Chart styling defaults and card options, set by the UI apps from their odoo
# config (single `kt.config` record :
# {"graph": {"layout": {...}}, "card": {"comparison": bool}})
CHART_CONFIG = settings.CONFIG  # the same dict : see `kpiten_core.config`


def set_chart_config(config: dict):
    """Apply the odoo-side chart defaults (see kt.get_chart_config)."""
    settings.set_config(config)


def comparison_enabled() -> bool:
    """Whether the cards may show their comparison with the previous period.

    The switch of `kt.config` ; on when Odoo says nothing (no config record, an
    older kpiten module), so the cards defined with `compare = true` keep it.
    """
    return settings.comparison_enabled()


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


def pivot_case(content, table, store, full_predicates, field_labels=None):
    pivot_json = spec.load(content, "pivot")
    index = pivot_json["rows"]
    column = pivot_json["columns"]
    measure = pivot_json["measure"]
    aggregation = pivot_json.get("aggregation", "sum")
    monthly = pivot_json.get("grain") == "month"

    df = _resolve_table(store, pivot_json.get("from", table))
    df = filter_df(df, full_predicates)
    df = derive_columns(df, pivot_json.get("computed") or {})
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
    pivoted = cells.pivot(
        index=index, on=column, values=measure, aggregate_function="first"
    )
    # the header of the rows : the only column name a pivot shows
    fields = _fields(pivot_json, table, field_labels)
    shown = labels.column_label(index, pivot_json.get("labels"), fields)
    if shown != index and shown not in pivoted.columns:
        pivoted = pivoted.rename({index: shown})
    return _table(pivoted, pivot_json)


TOTAL = "Total"


def _data_display(line: dict, df: pl.DataFrame, table: str, field_labels):
    """The `[labels]` and the `[table]` of a data tile (its `display` field, the header
    of its SQL : `spec.display`). The visible columns named after a field take its
    label in Odoo ; the others (`Revenue`, an alias of the SQL) stay as they are."""
    try:
        display = spec.display(line["content"], line.get("display"))
    except Exception as err:
        raise TileError(f"display : {err}") from err
    tile_labels = display.get("labels") or {}
    fields = field_labels(table) if field_labels is not None else {}
    renamed = {}
    for column in df.columns:
        if column in tile_labels or (column in fields and column != "id"):
            shown = labels.column_label(column, tile_labels, fields)
            if shown != column and shown not in df.columns:
                renamed[column] = shown
    if renamed:
        df = df.rename(renamed)
        table_json = display.get("table") or {}
        if table_json.get("columns"):  # written with the names of the columns
            table_json["columns"] = {
                renamed.get(k, k): v for k, v in table_json["columns"].items()
            }
    return _table(df, display, stub=False)


def _table(
    df: pl.DataFrame, tile_json: dict, stub: bool = True
) -> tuple[pl.DataFrame, dict]:
    """The `[table]` of a pivot or a data tile : its « Total » column added to the rows,
    and what the front draws (`meta["table"]`, see `render.gtable`) : the formats, the
    « Total » row computed on every row (the front shows the first ones only), the
    heatmap... `stub` : the first column as row headers, by default."""
    table_json = tile_json.get("table")
    if not table_json and not tile_json.get("limit"):
        return df, {}
    table_json = {"stub": stub, **(table_json or {})}
    values = [c for c in df.columns[1:] if df.schema[c].is_numeric()]
    if table_json.pop("row_totals", False) and values and TOTAL not in df.columns:
        df = df.with_columns(pl.sum_horizontal(values).alias(TOTAL))
    drawing = {key: value for key, value in table_json.items() if key != "totals"}
    drawing["values"] = values  # the heatmap : the cells, not the totals
    if table_json.get("totals") and df.width > 1:
        row = {df.columns[0]: TOTAL}
        row.update(
            {c: df[c].sum() for c in df.columns[1:] if df.schema[c].is_numeric()}
        )
        drawing["totals"] = row
    if tile_json.get("limit"):
        drawing["limit"] = tile_json["limit"]
    return df, drawing


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


HIDDEN_PREFIX = "__"


def split_keys(df: pl.DataFrame) -> tuple[pl.DataFrame, list[dict] | None]:
    """Take the hidden columns (`__product_id_`...) out of a `data` result : the table
    does not show them, the click on a row hands them to the drill-down as `key`
    (`key["product_id_"]`). Returns the visible table and one dict per row (None
    when there is no hidden column)."""
    hidden = [c for c in df.columns if c.startswith(HIDDEN_PREFIX)]
    if not hidden:
        return df, None
    renamed = {c: c[len(HIDDEN_PREFIX) :] for c in hidden}
    return df.drop(hidden), df.select(hidden).rename(renamed).to_dicts()


def exec_drill(
    line: dict,
    table: str,
    store: dict[str, pl.DataFrame | pl.LazyFrame],
    full_predicates: list[pl.Expr],
    key: dict,
) -> TileResult:
    """The rows behind a row of a `data` tile : the `drill` snippet of the line.

    It runs on the same rows as the tile (the user's rights and the panel period and
    filters are kept) with `key`, the hidden columns of the clicked row, as a variable.
    The result is capped like any table (`TILE_MAX_ROWS`). `tables` gives the other tables.
    """
    drill = line.get("drill")
    if not drill:
        raise TileError(f"tile '{line.get('name')}' has no drill-down")
    if not all(
        isinstance(v, (str, int, float, bool, type(None))) for v in key.values()
    ):
        raise TileError("the key of a drill-down holds plain values only")
    label = f"{line.get('name') or 'tile'} : detail"
    try:
        # the other tables of the store are there too, filtered like the tile : a drill
        # can read the lines of an order (`tables["sale.order.line"]`)
        tables = {
            name: filter_df(_resolve_table(store, name), full_predicates)
            for name in store
        }
        df = dataframe_case(
            drill, table, store, full_predicates, {"key": key, "tables": tables}
        )
        df, meta = cap_rows(df)
        df, _ = split_keys(df)
        return TileResult("data", label, df=df, meta=meta)
    except TileError:
        raise
    except Exception as err:
        logger.error("Could not run the drill-down of %s", label, exc_info=True)
        raise TileError(f"Error drill-down '{label}' : {err}") from err


def dataframe_case(content, table, store, full_predicates, extra_variables=None):
    """Run the `data` kind definition : SQL (`sqltile`), or a polars snippet through the
    sandbox.

    The snippet's first line `d_next = d ` holds the input/output vars ; the SQL reads
    the table `d`. `extra_variables` are more read-only names for the snippet (the
    drill-down's `key`, and its `tables`) ; the SQL gets the tables by their name and
    the values of `key` as `:name`.
    """
    lazy = filter_df(_resolve_table(store, table), full_predicates)
    variables = {"odoo_url": links.get_odoo_url(), **(extra_variables or {})}
    if sqltile.is_sql(content):
        tables = {**variables.pop("tables", {}), "d": lazy}
        key = variables.pop("key", None) or {}
        return sqltile.run(content, tables, {**variables, **key})
    first_line = content.partition("\n")[0]
    out_var = first_line.split(" ")[0]
    df_var = first_line.split(" ")[2]
    try:
        return sandbox.run(content, lazy, df_var, out_var, variables)
    except AttributeError:
        # the snippet uses an eager-only method (pivot, transpose, describe...) :
        # give it the filtered rows in memory
        return sandbox.run(content, _collect(lazy), df_var, out_var, variables)


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
