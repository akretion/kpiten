"""Mock-up of a more attractive Shiny front (docs/refonte.md, section 5).

The same core as the dashboard (`exec_tile`, the period filters, `render.plotly`), on the
sample data of the kpiten-core tests (no Odoo needed) ; only the look changes :
a side bar for the filters, the cards as value boxes (an icon, a sparkline), the other
tiles as cards (an icon, an info tooltip, full screen), the tables as data grids, the
light / dark mode, the busy indicators of Shiny.

    cd src/shiny-kpiten && .venv/bin/python -m shiny run mockup/app.py --port 5010
"""

import json
import pathlib
import re

import faicons
import polars as pl
from shiny import App, reactive, render, ui

from kpiten_core import filters
from kpiten_core import tiles as core_tiles
from kpiten_core.render.plotly import _with_alpha

DATA = pathlib.Path(__file__).parents[2] / "kpiten-core" / "tests" / "data"
STORE = {p.stem: pl.read_parquet(p).lazy() for p in DATA.glob("*.parquet")}
TILES = [
    {**t, "id": i, "content": t["definition"]}
    for i, t in enumerate(json.loads((DATA / "tiles.json").read_text()))
]
PANELS = sorted({t["panel"] for t in TILES})
TABLES = ("data", "pivot", "union")
# the icon of a card, by the words of its name
# (words, icon, color) : the badge tells the kind of figure at a glance
ICONS = [
    (r"late|days", "clock", "#f59e0b"),
    (r"quotation|rfq", "file-invoice", "#8b5cf6"),
    (r"revenue|amount|value|spend|average", "sack-dollar", "#10b981"),
    (r"best", "trophy", "#ec4899"),
    (r"order|purchased", "cart-shopping", "#3b82f6"),
]
ACCENT = "#4f7cff"
GRAPH_ICON = {"graph": "chart-column", "pivot": "table-cells", "data": "table-list"}
MUTED = "#8a93a3"  # the text of the graphs : read on a light and a dark page


def icon(name: str, **kw):
    return faicons.icon_svg(name, **kw)


def card_icon(name: str) -> tuple[str, str]:
    for pattern, glyph, color in ICONS:
        if re.search(pattern, name, re.I):
            return glyph, color
    return "chart-line", ACCENT


def badge(name: str):
    glyph, color = card_icon(name)
    return ui.div(
        icon(glyph, fill=color, width="1.4rem", height="1.4rem"),
        class_="badge-icon",
        style=f"background: color-mix(in srgb, {color} 15%, transparent)",
    )


def plot_html(fig, height: int) -> ui.HTML:
    """A plotly figure drawn for both modes : transparent, muted text, no toolbar."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=MUTED, size=11, family="Inter, sans-serif"),
        margin=dict(l=8, r=8, t=8, b=8),
        height=height,
        colorway=["#4f7cff", "#16b3a6", "#f2a33a", "#e5566e", "#8e6cf1"],
    )
    fig.update_xaxes(gridcolor="rgba(138,147,163,.15)", title=None)
    fig.update_yaxes(gridcolor="rgba(138,147,163,.15)")
    for trace in fig.data:  # one accent color, rounded bars
        if trace.type == "bar":
            trace.marker.color = ACCENT
            trace.marker.cornerradius = 4
    return ui.HTML(
        fig.to_html(
            include_plotlyjs=False,
            full_html=False,
            config={"displayModeBar": False, "responsive": True},
        )
    )


def sparkline(tile, predicates, color=ACCENT):
    """The documents of the card's model per month, over the period : a trend line."""
    config = tile.get("filter_config") or {}
    field = filters.date_fields(config)
    frame = STORE.get(tile["model"])
    if not field or frame is None or field[0] not in frame.collect_schema():
        return None
    date = field[0]
    rows = (
        frame.filter(predicates or [pl.lit(True)])
        .group_by(pl.col(date).dt.truncate("1mo").alias("m"))
        .agg(pl.len().alias("n"))
        .sort("m")
        .collect()
    )
    if rows.height < 2:
        return None
    import plotly.graph_objects as go

    fig = go.Figure(
        go.Scatter(
            x=rows["m"],
            y=rows["n"],
            mode="lines",
            line=dict(width=2, color=color),
            fill="tozeroy",
            fillcolor=_with_alpha(color, 0.15),
            hoverinfo="skip",
        )
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(showlegend=False)
    return plot_html(fig, 60)


CSS = """
:root { --bs-font-sans-serif: Inter, system-ui, sans-serif; }
body { background: var(--bs-tertiary-bg); }
.bslib-value-box, .card { border: 0; border-radius: 14px;
  box-shadow: 0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08);
  transition: transform .15s ease, box-shadow .15s ease; }
.card:hover { transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(16,24,40,.10); }
.card-header { background: transparent; border-bottom: 0; font-weight: 600;
  display: flex; align-items: center; gap: .5rem; }
.card-header .tile-icon { color: var(--bs-primary); }
.card-header .info { margin-left: auto; opacity: .5; cursor: help; }
.badge-icon { width: 3rem; height: 3rem; border-radius: 12px; display: grid;
  place-items: center; }
.value-box-title { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em;
  opacity: .7; }
.value-box-value { font-weight: 700; }
.kpi-delta { font-size: .8rem; font-weight: 600; }
.kpi-delta.good { color: #16a34a; } .kpi-delta.bad { color: #dc2626; }
.sidebar-title { font-weight: 700; }
.brand { display: flex; align-items: center; gap: .5rem; font-weight: 700; }
.brand img { height: 32px; }
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.div(ui.tags.img(src="static/kpiten.png"), "KpiTen", class_="brand"),
        ui.input_select("panel", "Panel", PANELS, selected=PANELS[-1]),
        ui.output_ui("period"),
        ui.hr(),
        ui.tooltip(
            ui.input_dark_mode(id="mode"),
            "Light or dark : it follows the system, click to change",
        ),
        open="desktop",
        width=260,
    ),
    ui.head_content(
        ui.tags.link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap",
        ),
        ui.tags.script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
        ui.tags.style(CSS),
    ),
    ui.busy_indicators.use(spinners=True, pulse=True),
    ui.output_ui("board"),
    title=ui.output_text("title"),
    fillable=False,
)


def server(input, output, session):
    @reactive.calc
    def panel_tiles():
        return [t for t in TILES if t["panel"] == input.panel()]

    @reactive.calc
    def config():
        tiles = panel_tiles()
        return (tiles[0].get("filter_config") or {}) if tiles else {}

    @render.ui
    def period():
        span = filters.date_range(STORE, config())
        options = filters.date_options(span)
        return ui.input_select(
            "date",
            "Period",
            options,
            selected=filters.default_date_option(options, span),
        )

    @render.text
    def title():
        return input.panel()

    @reactive.calc
    def predicates():
        option = input.date() if "date" in input else None
        return filters.make_predicates(config(), filters.bounds_of_option(option), {})

    @reactive.calc
    def results():
        out = []
        for tile in panel_tiles():
            try:
                result = core_tiles.exec_tile(tile, tile["model"], STORE, predicates())
                out.append((tile, result, None))
            except Exception as err:
                out.append((tile, None, str(err).splitlines()[0][:200]))
        return out

    def value_box(tile, result):
        delta = []
        if result.comparison:
            c = result.comparison
            tone = "good" if c.get("tone", "good") == "good" else "bad"
            delta = [
                ui.span(f"{c['text']} {c['description']}", class_=f"kpi-delta {tone}")
            ]
        return ui.value_box(
            tile["name"],
            result.text,
            *delta,
            sparkline(tile, predicates(), card_icon(tile["name"])[1]) or "",
            showcase=badge(tile["name"]),
            showcase_layout="left center",
            max_height="170px",
        )

    def tile_card(tile, result, error):
        header = ui.card_header(
            ui.span(
                icon(GRAPH_ICON.get(tile["kind"], "table-list")), class_="tile-icon"
            ),
            tile["name"],
            ui.tooltip(
                ui.span(icon("circle-info"), class_="info"),
                filters.describe_filters(
                    config(),
                    filters.bounds_of_option(input.date() if "date" in input else None),
                    {},
                )
                or "No filter",
            ),
        )
        if error:
            body = ui.p(error, class_="text-danger small")
        elif result.kind == "graph":
            body = plot_html(result.figure, 280)
        else:
            body = ui.output_data_frame(f"grid_{tile['id']}")
        return ui.card(header, body, full_screen=True, min_height="360px")

    @render.ui
    def board():
        cards, blocks = [], []
        for tile, result, error in results():
            if tile["kind"] == "card" and result is not None:
                cards.append(value_box(tile, result))
            elif tile["kind"] != "card":
                blocks.append(tile_card(tile, result, error))
        return ui.TagList(
            ui.layout_column_wrap(*cards, width="220px", fill=False) if cards else None,
            ui.br(),
            ui.layout_column_wrap(*blocks, width="420px", fill=False),
        )

    # a data grid per table tile : sort, filter, scroll
    def grid(tile):
        def _grid():
            for t, result, _error in results():
                if (
                    t["id"] == tile["id"]
                    and result is not None
                    and result.df is not None
                ):
                    return render.DataGrid(
                        result.df.head(500), filters=True, height="300px"
                    )
            return None

        _grid.__name__ = f"grid_{tile['id']}"
        return render.data_frame(_grid)

    for tile in TILES:
        if tile["kind"] in TABLES:
            grid(tile)


app = App(
    app_ui,
    server,
    static_assets={
        "/static": pathlib.Path(__file__).parents[1] / "src" / "shiny_kpiten" / "static"
    },
)
