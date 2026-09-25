"""

Shiny dashboard app on top of kpiten-core.

The tiles are rendered as raw html (all content is written server-side) :
- card  -> big value
- graph -> plotly figure (to_html ; plotly.js is loaded once, in the page head)
- pivot / union / data -> great_tables themed table (see themes.py), or an
  interactive grid (sort, filter) when the tile asks for it (`table_view = grid`)

Themes and their palette live in `themes.py` (default = the one of `kt.config`) ; the
theme can be picked in the UI bar, and is then kept in Odoo for the user.
"""

import asyncio
import datetime
import json
import logging
import os
import pathlib
import re
import tempfile

from html import escape as html_escape

import faicons
import plotly.graph_objects as go
import polars as pl
from shiny import App, reactive, render, req, ui
from shiny.types import SilentException

from kpiten_core import anonymize, brand, comparison, i18n, links, llm, querychat
from kpiten_core import config as core_config
from kpiten_core import ods as core_ods
from kpiten_core import labels as core_labels
from kpiten_core import plugins as core_plugins
from kpiten_core.render.gtable import DRILL_CSS
from kpiten_core.render.plotly import _with_alpha, apply_theme_colors, finish
from kpiten_core import themes as core_themes
from kpiten_core import tiles as core_tiles
from kpiten_core.backend import Backend

from . import data as data_layer
from . import filterstate
from . import themes
from .sessions import SESSION_COOKIE, SessionHandler

STATIC_DIR = pathlib.Path(__file__).parent / "static"

logger = logging.getLogger(__name__)

# html of the last rendering, to look at the tiles (KPITEN_LOG_DIR is set by
# scripts/kpiten-stack : data/logs)
TILES_DUMP = (
    pathlib.Path(os.environ.get("KPITEN_LOG_DIR") or tempfile.gettempdir())
    / "kpiten_tiles.html"
)

PLOTLY_JS = "https://cdn.plot.ly/plotly-2.35.2.min.js"
# the KpiTen icon (the one of the Odoo menu), in the tab ; relative like the logo :
# it works at the app root and under /dashboard
FAVICON = ui.tags.link(rel="icon", type="image/png", href="static/kpiten.png")

REFRESH_TOOLTIP = "Refresh data : sync with Odoo now, to see its latest changes"
ODS_TOOLTIP = "Download the rows of an Odoo model as a spreadsheet"
# a spreadsheet (a grid with its header row), in the color of the text
SPREADSHEET_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" aria-hidden="true">'
    '<rect x="3" y="3" width="18" height="18" rx="2"/>'
    '<path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>'
)
ODS_MODEL_TOOLTIP = (
    "Download as a spreadsheet : the rows of this model you may read, with the "
    "filters of the panel"
)
EDIT_TOOLTIP = (
    "Edit this panel : move, resize or delete its tiles (drag and drop, or the "
    "buttons on each tile). The changes are saved in Odoo."
)
AI_TOOLTIP = "Ask the AI : narrow the rows of this KPI in words"
TAB_TITLE = "KpiTen (shiny)"  # the name of the browser tab, after the panel

# the grid has 6 columns : a tile of width 1 takes a third of the row, 2 a half, 3 the
# whole row (two tiles of width 2 sit side by side, none leaves a hole)
GRID_SPAN = {1: 2, 2: 3, 3: 6}

HEIGHT_STEP = 40  # px ; tile_height resize step in edit mode
WIDTH_MIN = 1
WIDTH_MAX = 3


def span_of(line: dict) -> int:
    """Columns of the grid a tile takes."""
    return GRID_SPAN.get(line.get("col_span") or 1, 2)


def dim_input_id(column: str) -> str:
    """Stable input id for a dimension column (i.e. 'user_id.name')."""
    return "dim_" + re.sub(r"[^A-Za-z0-9_]", "_", column)


EDIT_MODE_JS = """
(function () {
  // every grid in edit mode : the row of the cards, and the one of the other tiles
  document.querySelectorAll(".tile-grid--edit").forEach(function (grid) {
  // toolbar actions -> Shiny input (server applies the change and re-renders)
  grid.addEventListener("click", function (e) {
    const btn = e.target.closest(".tile-act");
    if (!btn || !window.Shiny) { return; }
    const item = btn.closest("[data-tile-id]");
    Shiny.setInputValue("tile_action",
        {id: item.dataset.tileId, action: btn.dataset.action},
        {priority: "event"});
  });
  // native html5 drag & drop reorder
  grid.addEventListener("dragstart", function (e) {
    const item = e.target.closest(".tile-edit-item");
    if (!item) { return; }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", item.dataset.tileId);
  });
  grid.addEventListener("dragover", function (e) { e.preventDefault(); });
  grid.addEventListener("drop", function (e) {
    e.preventDefault();
    const src = e.dataTransfer.getData("text");
    const dropEl = e.target.closest(".tile-edit-item");
    const dragEl = grid.querySelector('[data-tile-id="' + src + '"]');
    if (!src || !dropEl || !dragEl || dropEl === dragEl) { return; }
    grid.insertBefore(dragEl, dropEl);
    if (!window.Shiny) { return; }
    const ids = Array.from(grid.querySelectorAll(".tile-edit-item"))
        .map(function (i) { return i.dataset.tileId; });
    Shiny.setInputValue("tile_order", ids, {priority: "event"});
  });
  });
})();
"""


# On page load: apply the `?theme=` url param. The theme the user chose is kept in
# Odoo (`kt.user.theme`) : the server selects it.
THEME_PERSIST_JS = """
(function () {
  if (window.__kpitenThemeInit) { return; }
  window.__kpitenThemeInit = true;
  function persisted() {
    return new URLSearchParams(window.location.search).get("theme");
  }
  function applyPersisted(tries) {
    const saved = persisted();
    if (!saved) { return; }
    if (window.Shiny) { Shiny.setInputValue("theme", saved, {priority: "event"}); }
    // the dropdown is drawn by the server, a moment after the page : wait for it
    const el = document.querySelector("#theme");
    if (!el) {
      if (tries < 100) { setTimeout(function () { applyPersisted(tries + 1); }, 100); }
      return;
    }
    if (el.selectize) { el.selectize.setValue(saved, true); return; }
    const known = Array.prototype.some.call(el.options, function (o) { return o.value === saved; });
    if (known && el.value !== saved) {
      el.value = saved;  // a native <select> : show it
      el.dispatchEvent(new Event("change", {bubbles: true}));
    }
  }
  setTimeout(function () { applyPersisted(0); }, 100);
})();
"""


def user_lang(sso) -> str | None:  # noqa: ANN001
    """The Odoo language of the user : the one of the SSO login, else (dev mode) the
    one of the rpc login user."""
    if sso is not None:
        return sso.lang
    try:
        backend = Backend.create()
        return backend.get_user_lang(backend.current_user_id())
    except Exception:
        logger.exception("the language of the rpc user is unknown")
        return None


def tiles_and_chat(tr):  # noqa: ANN001
    """The tiles ; with an AI model configured (`kpiten_core.llm`), the chat that
    narrows a tile in words, on their right, closed until a ✨ of a tile opens it."""
    tiles = ui.div(ui.output_ui("tiles"))
    if llm.default_provider() is None:
        return tiles
    return ui.layout_sidebar(
        ui.sidebar(
            ui.output_ui("ai_head"),
            ui.chat_ui(
                "ai_chat",
                placeholder=tr("Narrow this KPI in words…"),
                drawer=False,
                width="100%",
                height="auto",
            ),
            id="ai_sidebar",
            position="right",
            open="closed",
            width=380,
            class_="kpiten-ai",
        ),
        tiles,
        border=False,
        fillable=False,
        class_="kpiten-ai-layout",
    )


def app_ui(req):  # noqa: ANN001
    from kpiten_core import env

    sso = SessionHandler.get(req.cookies.get(SESSION_COOKIE))
    if not env.allow_rpc_user and not sso:
        tr = i18n.translator(req.headers.get("accept-language"))
        return ui.page_fluid(
            {"class": "kpiten-dashboard"},
            ui.head_content(FAVICON),
            ui.h3(tr("Not connected")),
            ui.p(
                tr(
                    "Open the dashboard from Odoo : menu KpiTen → {front}.",
                    front="Shiny",
                )
            ),
            title=f"{tr('Not connected')} · {TAB_TITLE}",
        )
    tr = i18n.translator(user_lang(sso))
    # the hexagon of Shiny ; relative : works at app root and under /dashboard
    logo = "static/shiny.png"
    return ui.page_fluid(
        {"class": "kpiten-dashboard", "lang": tr.lang},
        # loaded once, before any tile : a figure that loaded it itself could run
        # before the script was there ("Plotly is not defined")
        ui.head_content(
            FAVICON,
            ui.tags.script(src=PLOTLY_JS),
            ui.tags.script(FULLSCREEN_JS),
            # the scripts and styles of the plugins' tiles (kpiten_core.hookspecs)
            ui.HTML(core_plugins.head_html()),
        ),
        ui.output_ui("theme_style"),
        ui.output_ui("tab_title"),
        # shiny shows the page is working : a spinner on a tile, a line on top
        ui.busy_indicators.use(spinners=True, pulse=True),
        ui.layout_sidebar(
            # the side bar : what the page shows (panel, filters) and how (theme)
            ui.sidebar(
                # who is looking : the user of Odoo (the rights of the tiles are theirs)
                ui.output_ui("user_name"),
                ui.input_select("panel", tr("Panel"), choices=[], width="100%"),
                ui.output_ui("filters"),
                ui.output_ui("theme_select"),
                ui.output_ui("db_select"),
                ui.tags.span(
                    ui.input_switch("edit_mode", tr("Edit"), False),
                    title=tr(EDIT_TOOLTIP),
                ),
                ui.div(ui.HTML(brand.lockup_svg(64)), title=brand.tooltip()),
                ui.output_ui("edit_lock"),
                id="sidebar",
                open="desktop",
                width=260,
                class_="kpiten-sidebar",
            ),
            # the head of the page : the panel, its actions, the freshness of the data
            ui.div(
                ui.h2(ui.output_text("panel_title", inline=True)),
                ui.input_action_button(
                    "refresh_data",
                    ui.HTML(svg("rotate")),
                    class_="btn-kpiten",
                    title=tr(REFRESH_TOOLTIP),
                ),
                ui.output_ui("ods_button"),
                # the exports of the panel the plugins offer (quarto-kpiten : a PDF)
                ui.output_ui("plugin_exports"),
                ui.output_ui("data_freshness"),
                class_="top-bar",
            ),
            tiles_and_chat(tr),
            # at the end of the page, on the right : the logo of the framework, then
            # the one of KpiTen with its name
            ui.div(
                ui.tags.a(
                    ui.span(tr("Built with")),
                    ui.tags.img(
                        src=logo, alt="Shiny for python", class_="framework-logo"
                    ),
                    href="https://shiny.posit.co/py",
                    title=tr("Made with Shiny"),
                    target="_blank",
                    class_="framework-credit",
                ),
                class_="app-footer",
            ),
            border=False,
            fillable=False,
            class_="kpiten-layout",
        ),
        title=TAB_TITLE,
    )


# the badge of a card, by the words of its name : the kind of figure at a glance
CARD_ICONS = [
    (r"late|delay", "clock", "#f59e0b"),
    (r"days|lead", "hourglass-half", "#f59e0b"),
    (r"quotation|rfq", "file-invoice", "#8b5cf6"),
    (r"revenue|amount|value|spend|average|margin", "sack-dollar", "#10b981"),
    (r"best|top", "trophy", "#ec4899"),
    (r"order|purchased|sold", "cart-shopping", "#3b82f6"),
]
CARD_ICON = ("chart-line", "#4f7cff")
TILE_ICONS = {
    "graph": "chart-column",
    "pivot": "table-cells",
    "data": "table-list",
    "union": "layer-group",
}


def svg(name: str, **kwargs) -> str:
    return str(faicons.icon_svg(name, **kwargs))


def card_icon(name: str) -> tuple[str, str]:
    for pattern, glyph, color in CARD_ICONS:
        if re.search(pattern, name or "", re.I):
            return glyph, color
    return CARD_ICON


def card_badge(name: str) -> str:
    glyph, color = card_icon(name)
    return (
        f'<span class="badge-icon" style="background: color-mix(in srgb, {color} 16%, '
        f'transparent)">{svg(glyph, fill=color, width=".9rem", height=".9rem")}</span>'
    )


def tile_header(line: dict, kind: str, info: str, tr=i18n.english, ai: str = "") -> str:
    """The title of a tile : its icon, its name, its kind ; the filters it was
    computed with (an info icon), the AI (`ai`, see `ai_html`) and the full screen
    button on the right."""
    info_icon = (
        f'<span class="tile-info" title="{info}">{svg("circle-info")}</span>'
        if info
        else ""
    )
    return (
        f'<h3><span class="tile-icon">{svg(TILE_ICONS.get(kind, "table-list"))}</span>'
        f'<span class="tile-name">{line["name"] or kind}</span>'
        f'<span class="kind-badge">{tr(kind)}</span>'
        f'<span class="tile-actions">{ai}{info_icon}'
        f'<button type="button" class="tile-full" title="{tr("Full screen (Esc to leave)")}">'
        f"{svg('expand')}</button></span></h3>"
    )


def grid_rows(df: pl.DataFrame) -> pl.DataFrame:
    """The rows of an interactive grid : a `[label](url)` link is its label (a grid
    shows text ; the links stay in the table view)."""
    return df.with_columns(
        pl.col(name).str.replace(r"^\[(.*)\]\(https?://[^)]*\)$", "$1")
        for name, dtype in df.schema.items()
        if dtype == pl.String
    )


# the javascript of `ui.output_data_frame` : a grid output written in the html of a tile
# (a string) comes without it
GRID_DEPENDENCIES = ui.output_data_frame("grid").get_dependencies()

# a tile in full screen : the button of its title ; Esc gives the page back
FULLSCREEN_JS = """
(function () {
  if (window.__kpitenFull) { return; }
  window.__kpitenFull = true;
  function resize() { window.dispatchEvent(new Event("resize")); }
  document.addEventListener("click", function (e) {
    var button = e.target.closest(".tile-full");
    if (!button) { return; }
    e.stopPropagation();
    button.closest(".tile").classList.toggle("tile--full");
    resize();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    document.querySelectorAll(".tile--full").forEach(function (t) {
      t.classList.remove("tile--full");
    });
    resize();
  });
})();
"""


def _inject_toolbar(content: str, line: dict, tr=i18n.english) -> str:
    """Insert the edit toolbar after the tile's h3 title.

    Icons + tooltips only, to keep the interface light.
    """
    actions = [
        ("left", "◀", "Move left"),
        ("right", "▶", "Move right"),
        ("winc", "⇥", "Wider"),
        ("wdec", "⇤", "Narrower"),
        ("hinc", "⤒", "Taller"),
        ("hdec", "⤓", "Shorter"),
        ("delete", "🗑", "Delete"),
    ]
    toolbar = "".join(
        f'<button class="tile-act" data-action="{key}" title="{tr(label)}" '
        f'aria-label="{tr(label)}">{icon}</button>'
        for key, icon, label in actions
    )
    block = f'<div class="tile-tools"><span class="tile-id">#{line["id"]}</span>{toolbar}</div>'
    idx = content.find("</h3>")
    if idx > 0:
        return content[: idx + 5] + block + content[idx + 5 :]
    return block + content


# a click on a row of a drillable table tells the server which tile and which row
# (the hidden key columns of the row stay on the server)
DRILL_JS = """
(function () {
  if (window.__kpitenDrill) { return; }
  window.__kpitenDrill = true;
  document.addEventListener("click", function (ev) {
    if (ev.target.closest("a")) { return; }
    var row = ev.target.closest(".tile.drillable .gt_table tbody tr");
    if (!row || !window.Shiny) { return; }
    var tile = row.closest(".tile");
    var rows = Array.prototype.slice.call(tile.querySelectorAll(".gt_table tbody tr"));
    Shiny.setInputValue("drill_click",
      {line: parseInt(tile.dataset.tileId, 10), row: rows.indexOf(row)},
      {priority: "event"});
  });
})();
"""

# ✨ on a tile opens the chat about it ; × on its badge removes the filter the AI made
AI_JS = """
(function () {
  if (window.__kpitenAi) { return; }
  window.__kpitenAi = true;
  document.addEventListener("click", function (ev) {
    var button = ev.target.closest(".tile-ai, .tile-ai-clear");
    if (!button || !window.Shiny) { return; }
    ev.stopPropagation();
    var tile = button.closest("[data-tile-id]");
    Shiny.setInputValue(
      button.classList.contains("tile-ai") ? "ai_tile" : "ai_clear",
      parseInt(tile.dataset.tileId, 10), {priority: "event"});
  });
})();
"""


def ai_html(where: dict | None, tr=i18n.english) -> str:
    """The ✨ button of a tile, and the badge of the filter the AI made for it
    (`where` : {"title", "where"}, None without one) : its SQL in the tooltip."""
    button = (
        f'<button type="button" class="tile-ai" title="{html_escape(tr(AI_TOOLTIP))}">'
        f'{svg("wand-magic-sparkles")}</button>'
    )
    if not where:
        return button
    tooltip = tr("AI filter : {title}", title=where["title"]) + "\n" + where["where"]
    return (
        f'<span class="tile-ai-filter" title="{html_escape(tooltip, quote=True)}">'
        f'<span>{html_escape(where["title"])}</span>'
        f'<button type="button" class="tile-ai-clear" '
        f'title="{html_escape(tr("Remove the AI filter"), quote=True)}">×</button></span>'
        + button
    )


# ---- tiles html rendering ---------------------------------------------
def records_link_html(records: dict | None, tr=i18n.english) -> str:
    """The link under a table that lists Odoo records : the same list, in Odoo (the
    rights of the user apply there). `records` is `core_tiles.records_link`."""
    if not records:
        return ""
    count, total = records["count"], records["total"]
    label = (
        tr("Open these {count} records in Odoo", count=count)
        if count == total
        else tr(
            "Open the first {count} of {total} records in Odoo",
            count=count,
            total=total,
        )
    )
    title = tr("The same list of records, in Odoo (with your rights)")
    return (
        f'<a class="records-link" href="{html_escape(records["url"], quote=True)}" '
        'target="_blank" rel="noopener noreferrer" '
        f'title="{html_escape(title, quote=True)}">'
        f"{label}</a>"
    )


def tile_html(
    line: dict,
    theme: themes.Theme,
    result: core_tiles.TileResult,
    info: str = "",
    records: dict | None = None,
    sparkline: str = "",
    grid: bool = False,
    tr=i18n.english,
    ai: str = "",
) -> str:
    """Tile html ; `info` goes in a tooltip = active filters description ; `records` is
    the link that opens the listed records in Odoo (when the KPI lists some) ;
    `sparkline` the trend under a card's value ; `grid` : a table drawn as an
    interactive grid (`grid_<id>`, the server renders it) ; `tr` : the language of
    the user (`kpiten_core.i18n`) ; `ai` : the button that asks the AI about the tile,
    and the filter it made (`ai_html`)."""
    p = theme.palette
    tooltip = f' title="{info}"' if info else ""
    if result.kind == "card":
        # odoo-dashboard style kpi : compact single value, no big title
        return (
            f'<div class="tile kpi-card" data-tile-id="{line["id"]}"{tooltip}>'
            f'<div class="kpi-head">{card_badge(line["name"])}'
            f'<span class="kpi-label">{line["name"] or ""}</span>{ai}</div>'
            # a name (best seller...) is text : smaller, it can be long
            f'<div class="value{" kpi-text" if isinstance(result.value, str) else ""}">'
            f"{html_escape(result.text)}</div>"
            + (
                f'<div class="kpi-sub">{html_escape(result.subtitle)}</div>'
                if result.subtitle
                else ""
            )
            + (
                comparison.html_block(result.comparison, p, tr)
                if result.comparison
                else ""
            )
            + (f'<div class="kpi-trend">{sparkline}</div>' if sparkline else "")
            + "</div>"
        )
    parts = [tile_header(line, result.kind, info, tr, ai)]
    # a plugin may draw the tile (kpiten_core.hookspecs), e.g. perspective-kpiten
    plugged = core_plugins.render_tile(line, result, p)
    if plugged:
        parts.append(plugged)
    elif result.kind == "graph":
        apply_theme_colors(result.figure, p)
        result.figure.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=p["text"], size=11),
            margin=dict(l=10, r=10, t=30, b=20),
        )
        finish(result.figure, result.chart)  # the [plotly] of the tile : last
        parts.append(result.figure.to_html(include_plotlyjs=False, full_html=False))
    elif grid and result.df is not None:
        # sorted and filtered by the user : the server renders `grid_<id>`
        parts.append(str(ui.output_data_frame(f"grid_{line['id']}")))
    else:
        assert result.df is not None
        # the rows of `kt.config` shown (or the `limit` of the tile) : the tile
        # scrolls, the page does not grow
        drawing = result.meta.get("table")
        rows = (drawing or {}).get("limit") or core_config.table_rows()
        parts.append(themes.gt_df(theme, result.df.head(rows), drawing).as_raw_html())
        # out of what the tile holds (`total_rows` when the core already cut it off)
        total = result.meta.get("total_rows", result.df.height)
        if total > rows:
            result.meta["notes"] = [core_tiles.rows_note(rows, total)]
    note = result.note_in(tr)
    if note:
        # the tile was reduced to stay renderable (see kpiten_core.tiles)
        parts.append(
            f'<div style="font-size: 11px; opacity: .65; margin-top: 4px">'
            f"{note}</div>"
        )
    parts.append(records_link_html(records, tr))
    html = "".join(str(part) for part in parts)
    drillable = bool(line.get("drill")) and bool(result.keys) and not grid
    height = line.get("tile_height") or 260
    # a graph keeps the height of its tile ; a table is as tall as its rows, up to it
    size = (
        f"min-height: {max(height - 40, 120)}px"
        if result.kind == "graph" or plugged or grid
        else f"max-height: {max(height, 340)}px"
    )
    return (
        f'<div class="tile{" drillable" if drillable else ""}" '
        f'data-tile-id="{line["id"]}"{tooltip} style="grid-column: span {span_of(line)}; '
        f'{size}">{html}</div>'
    )


def tile_error_html(line: dict, error: str, info: str = "") -> str:
    error = error.replace('"', "'")
    tooltip = f' title="{info}"' if info else ""
    return (
        f'<div class="tile"{tooltip} style="grid-column: span {span_of(line)}">'
        f'<h3>{line["name"]}</h3>'
        f'<p style="color: #ff6e6f">{error}</p></div>'
    )


def server(input, output, session):
    from kpiten_core import env

    # who is connected : the SSO session of this browser (cookie), nothing is
    # shared with the other users. Only the dev mode (ALLOW_RPC_USER) runs
    # without one, as the rpc login user.
    sso = SessionHandler.get(session.http_conn.cookies.get(SESSION_COOKIE))
    if sso is None and not env.allow_rpc_user:
        return  # app_ui shows « log in from Odoo »

    # active odoo database : the sso session one (an SSO user is bound to it),
    # switched reactively by the Database select in dev mode (each db has its
    # own parquet snapshot)
    initial_backend = Backend.create(db=sso.db if sso else None)
    backend_rv = reactive.Value(initial_backend)
    env.current_db = initial_backend.db
    # the texts of the page, in the language of the user in Odoo (the labels of
    # the fields too : the names of the columns of the tiles)
    odoo_lang = (
        sso.lang
        if sso
        else initial_backend.get_user_lang(initial_backend.current_user_id())
    )
    tr = i18n.translator(odoo_lang)

    def current_user_id() -> int:
        """Odoo user of this session (dev mode : the rpc login user)."""
        return sso.user_id if sso else backend_rv().current_user_id()

    @reactive.calc
    def can_edit() -> bool:
        """Only a KpiTen manager of Odoo edits the tiles (the apps read Odoo with
        one rpc account : nothing else stops a user from sending an edit)."""
        return backend_rv().can_edit_tiles(current_user_id())

    @render.ui
    def edit_lock():
        """The switch stays in the page (a dynamic one would render the tiles twice,
        their render reads it) and is only hidden for a user who is not a manager."""
        if can_edit():
            return None
        return ui.tags.style(".shiny-input-container:has(#edit_mode) { display: none }")

    # the theme the user chose (kept in Odoo), None : the default of `kt.config`
    saved_theme = reactive.Value(
        core_themes.key(initial_backend.get_user_theme(current_user_id()))
    )

    # Apply the odoo-side chart defaults (colors) once per session.
    core_tiles.set_chart_config(initial_backend.get_chart_config())
    links.set_odoo_url(initial_backend.get_base_url())
    data_version = reactive.Value(0)
    layout_version = reactive.Value(0)

    def _progress_cb(p):
        """Return a sync progress callback feeding a ui.Progress bar.

        Rows are unknown up-front, so the bar reflects activity (one step per
        extracted page) and the detail shows the current model + rows so far.
        """
        totals: dict[str, int] = {}

        def cb(model, mode, offset, count, page_size):
            totals[model] = totals.get(model, 0) + count
            kind = {"full": "initial extract", "delta": "update"}.get(mode, "update")
            p.inc(
                1,
                detail=tr(
                    "{kind} : {model} — {count} records",
                    kind=tr(kind),
                    model=model,
                    count=totals[model],
                ),
            )

        return cb

    @reactive.effect
    def _db_changed():
        db = input.db()  # the select re-fires on init : switch only on change
        with reactive.isolate():
            if sso is not None or db == backend_rv().db or not db:
                return  # an SSO session is bound to its database
            new_backend = Backend.create(db=db)
            env.current_db = db
            backend_rv.set(new_backend)
            core_tiles.set_chart_config(new_backend.get_chart_config())
            links.set_odoo_url(new_backend.get_base_url())
            saved_theme.set(
                core_themes.key(new_backend.get_user_theme(current_user_id()))
            )
            data_version.set(data_version() + 1)
            layout_version.set(layout_version() + 1)
            ui.notification_show(tr("Database switched to {db}", db=db))

    @render.ui
    def user_name():
        """The name of the user in Odoo, at the top of the side bar."""
        backend = backend_rv()
        try:
            name = backend.get_user_name(current_user_id())
        except Exception:
            logger.exception("the name of the user is unknown")
            return None
        return ui.div(
            ui.HTML(svg("user")),
            ui.span(name),
            class_="kpiten-user",
            title=tr("Connected to {db} as {name}", db=backend.db, name=name),
        )

    @render.ui
    def db_select():
        """Odoo database selector (each db has its own parquet snapshot)."""
        try:
            databases = [sso.db] if sso else backend_rv().list_databases()
        except Exception:
            databases = [backend_rv().db]
        return ui.input_select(
            "db",
            tr("Database"),
            choices=databases,
            selected=backend_rv().db,
            width="100%",
        )

    @reactive.calc
    def panels():
        backend_rv()  # re-render on db switch
        ordered = backend_rv().get_panels()  # already sorted by sequence, id
        choices = {str(p["id"]): p["name"] for p in ordered}
        with reactive.isolate():
            try:
                current = str(int(input.panel()))  # keep the user selection
                if current not in choices:
                    current = None
            except (KeyError, TypeError):
                current = None
            if current is None:
                # default : first panel in sequence order
                current = str(ordered[0]["id"]) if ordered else None
        ui.update_select("panel", choices=choices, selected=current)
        return choices

    def user_theme() -> str:
        """The theme of the user : the one they chose, else the default of Odoo."""
        return saved_theme() or core_config.default_theme()

    @reactive.calc
    def current_theme() -> themes.Theme:
        if "theme" in input:
            try:
                return themes.get_theme(input.theme())
            except (KeyError, TypeError):
                pass
        return themes.get_theme(user_theme())

    @render.ui
    def theme_select():
        """Theme select, rendered once the app is up (and again on a db switch)."""
        choices = {key: t.name for key, t in themes.THEMES.items()}
        with reactive.isolate():
            selected = user_theme()
        backend_rv()
        return ui.input_select(
            "theme",
            tr("Theme"),
            choices=choices,
            selected=selected,
            width="100%",
        )

    @reactive.effect
    @reactive.event(input.theme)
    def _save_theme():
        """A theme chosen in the select is kept in Odoo for the user."""
        key = core_themes.key(input.theme())
        with reactive.isolate():
            if not key or key == user_theme():
                return
            backend_rv().set_user_theme(current_user_id(), key)
            saved_theme.set(key)

    @render.text
    def panel_title():
        """The name of the open panel, at the head of the page."""
        return panels().get(str(req(input.panel()))) or ""

    @render.ui
    def tab_title():
        """The tab names the open panel : `Sales · KpiTen (shiny)`."""
        name = panels().get(str(req(input.panel())))
        title = f"{name} · {TAB_TITLE}" if name else TAB_TITLE
        return ui.tags.script(f"document.title = {json.dumps(title)};")

    @render.ui
    def theme_style():
        return ui.tags.div(
            ui.tags.style("{}".format(current_theme().css())),
            ui.tags.script(THEME_PERSIST_JS),
            ui.tags.style(links.LINK_CSS + DRILL_CSS),
            ui.tags.script(links.NEW_TAB_JS),
            ui.tags.script(DRILL_JS),
            ui.tags.script(AI_JS),
        )

    @reactive.calc
    def store() -> dict[str, pl.LazyFrame]:
        data_version()
        backend = backend_rv()
        user_id = current_user_id()
        content = data_layer.user_store(backend, user_id)
        if not content:
            # fresh database : ask kpiten-core for a full connectorx extract
            with ui.Progress(min=1, max=100) as p:
                data_layer.request_refresh(backend.db, progress=_progress_cb(p))
            content = data_layer.user_store(backend, user_id)
        return content

    @render.ui
    def data_freshness():
        """Discrete data-age stamp (details in the tooltip)."""
        data_version()  # re-render after each sync
        backend = backend_rv()
        stamp = data_layer.last_sync(backend, current_user_id())
        if not stamp:
            return ui.tags.span("", class_="data-freshness")
        return ui.tags.span(
            "⏱ " + stamp,
            class_="data-freshness",
            title=tr(
                "Data as of {stamp} — parquet snapshot time ; ⟳ syncs with Odoo",
                stamp=stamp,
            ),
        )

    @reactive.calc
    def lines():
        req(input.panel())
        backend = backend_rv()
        layout_version()  # tiles layout changed (edit mode save/delete)
        res = backend.get_panel_tiles(int(input.panel()), current_user_id())
        logger.info(
            "lines : db=%s panel=%s count=%s", backend.db, input.panel(), len(res)
        )
        return res

    @reactive.calc
    def panel_settings() -> dict:
        req(input.panel())
        panel_id = int(input.panel())
        backend = backend_rv()
        try:
            return backend.get_panel_settings(panel_id)
        except (KeyError, IndexError):
            return {"filter_config": {}}

    # ---- filters from panel.filter_config ------------------------------
    @render.ui
    def filters():
        panels()
        req(input.panel())
        panel = panel_settings()
        config = panel.get("filter_config") or {}
        controls = []
        store_data = store()
        if config.get("date"):
            # the choices fit the data of the panel : windows, months or years it covers
            span = filterstate.date_range(store_data, config)
            options = filterstate.date_options(span)
            controls.append(
                ui.input_select(
                    "date_period",
                    tr("Period"),
                    # the keys stay the English ones (the value of the input)
                    choices={key: tr(label) for key, label in options.items()},
                    selected=filterstate.default_date_option(options, span),
                    width="100%",
                )
            )
        for dim in config.get("dimensions", []):
            choices = filterstate.dimension_choices(store_data, dim["name"])
            controls.append(
                ui.input_selectize(
                    dim_input_id(dim["name"]),
                    dim.get("label") or dim["name"],
                    choices=sorted(choices),
                    selected=[],
                    multiple=True,
                    width="100%",
                )
            )
        if controls:
            return ui.tags.div(*controls, class_="filter-bar")
        return ui.tags.div("")

    @reactive.calc
    def filter_state():
        """(panel filter config, period bounds, selected dimension values)."""
        current_panel = panel_settings()
        config = current_panel.get("filter_config") or {}
        date_value = None
        if "date_period" in input:
            period = input.date_period()
            date_value = filterstate.bounds_of_option(period)
        dim_values: dict[str, list] = {}
        for dim in config.get("dimensions", []):
            key = dim_input_id(dim["name"])
            if key in input:
                try:
                    dim_values[dim["name"]] = input[key]()
                except (KeyError, TypeError):
                    raise SilentException()
        return config, date_value, dim_values

    @reactive.calc
    def predicates():
        return filterstate.make_predicates(*filter_state())

    @reactive.calc
    def previous():
        """(predicates, label) of the period before the selected one, for the
        cards that compare themselves ; (None, None) without a period."""
        config, date_value, dim_values = filter_state()
        return (
            filterstate.make_previous_predicates(config, date_value, dim_values),
            filterstate.describe_previous(date_value),
        )

    def filters_text() -> str:
        """The panel filters that are set, as text."""
        config = panel_settings().get("filter_config") or {}
        date_value = (
            filterstate.bounds_of_option(input.date_period())
            if "date_period" in input
            else None
        )
        dim_values: dict[str, list] = {}
        for dim in config.get("dimensions", []):
            key = dim_input_id(dim["name"])
            if key in input:
                try:
                    dim_values[dim["name"]] = input[key]()
                except (KeyError, TypeError):
                    pass
        return filterstate.describe_filters(config, date_value, dim_values, tr)

    # ---- the raw rows of an Odoo model as a spreadsheet, with the user's rights
    @render.ui
    def ods_button():
        """The export is for who `kt.config` says (everyone, the managers, nobody)."""
        if not core_config.explore_allowed(can_edit()):
            return None
        return ui.input_action_button(
            "ods_open", "\u2913", class_="btn-kpiten", title=tr(ODS_TOOLTIP)
        )

    @reactive.effect
    @reactive.event(input.ods_open)
    def _ods_dialog():
        models = core_ods.exportable_models(store())
        ui.modal_show(
            ui.modal(
                ui.input_select("ods_model", None, models, width="100%"),
                title=tr("Download the rows of a model"),
                easy_close=True,
                size="s",
                footer=ui.download_button(
                    "ods",
                    ui.HTML(SPREADSHEET_ICON),
                    class_="btn-kpiten",
                    title=tr(ODS_MODEL_TOOLTIP),
                ),
            )
        )

    @render.download(
        filename=lambda: f"kpiten-{backend_rv().db}-{input.ods_model()}.ods",
        media_type="application/vnd.oasis.opendocument.spreadsheet",
    )
    def ods():
        with reactive.isolate():
            if not core_config.explore_allowed(can_edit()):
                raise PermissionError(tr("You may not export the rows."))
            _name, data, note = core_ods.model_ods(
                store(),
                input.ods_model(),
                predicates(),
                user_id=current_user_id(),
                db=backend_rv().db,
            )
        if note:
            ui.notification_show(f"{input.ods_model()} : {note}", type="warning")
        yield data

    def tile_info(line: dict) -> str:
        """Tooltip text : active panel filters + tile own WHERE (card)."""
        info = filters_text()
        if line["kind"] == "card":
            try:
                where = core_tiles.serial.loads(line["content"]).get("where")
                if where:
                    more = tr("Tile: {where}", where=where)
                    info = info + "\n" + more if info else more
            except Exception:
                pass
        where = ai_filters().get(line["id"])
        if where:
            more = tr("AI filter : {title}", title=where["title"])
            info = info + "\n" + more if info else more
        return info.replace('"', "'")

    def tile_edit_item(
        line: dict,
        theme: themes.Theme,
        result: core_tiles.TileResult,
        records: dict | None = None,
    ) -> str:
        """Same CSS-grid tile, draggable with an edit toolbar."""
        content = _inject_toolbar(
            tile_html(line, theme, result, tile_info(line), records, tr=tr), line, tr
        )
        return (
            f'<div class="tile-edit-item" data-tile-id="{line["id"]}"'
            f' draggable="true" style="grid-column: span {span_of(line)}">{content}</div>'
        )

    def tile_error_item_html(line: dict, error: str) -> str:
        content = _inject_toolbar(
            tile_error_html(line, str(error), tile_info(line)), line, tr
        )
        return (
            f'<div class="tile-edit-item" data-tile-id="{line["id"]}"'
            f' draggable="true" style="grid-column: span {span_of(line)}">{content}</div>'
        )

    # ---- data refresh effect (on-demand button) --------------------------
    @reactive.effect
    def _refresh():
        input.refresh_data()
        with reactive.isolate():
            backend = backend_rv()
            with ui.Progress(min=1, max=100) as p:
                data_layer.request_refresh(backend.db, progress=_progress_cb(p))
            data_version.set(data_version() + 1)
            ui.notification_show(tr("Data synced with Odoo."), duration=3)

    # ---- edit mode : layout save + tile delete -------------------------
    @reactive.effect
    def _tile_action():
        act = req(input.tile_action())  # dict {id, action} from EDIT_MODE_JS
        tile_id, action = int(act["id"]), act["action"]
        backend = backend_rv()
        with reactive.isolate():
            if not can_edit():
                ui.notification_show(tr("Only a KpiTen manager can edit tiles."))
                return

        with reactive.isolate():
            cur_lines = lines()
        by_id = {line["id"]: line for line in cur_lines}
        line = by_id.get(tile_id)
        if line is None:
            return

        if action == "delete":
            backend.delete_tile(tile_id)
            ui.notification_show(tr("Tile #{id} deleted", id=tile_id))

        elif action in ("winc", "wdec", "hinc", "hdec"):
            col_span = line.get("col_span") or 1
            tile_height = line.get("tile_height") or 260
            if action == "winc":
                col_span = min(WIDTH_MAX, col_span + 1)
            elif action == "wdec":
                col_span = max(WIDTH_MIN, col_span - 1)
            elif action == "hinc":
                tile_height += HEIGHT_STEP
            else:
                tile_height = max(HEIGHT_STEP, tile_height - HEIGHT_STEP)
            backend.update_tile_layout(tile_id, col_span, tile_height)

        else:  # left / right : swap with a neighbour, save the new sequence
            # the neighbour on screen : a card among the cards, a tile among the tiles
            card = line["kind"] == "card"
            ids = [l["id"] for l in cur_lines if (l["kind"] == "card") == card]
            pos = ids.index(tile_id)
            if action == "left" and pos > 0:
                ids[pos - 1], ids[pos] = ids[pos], ids[pos - 1]
            elif action == "right" and pos < len(ids) - 1:
                ids[pos + 1], ids[pos] = ids[pos], ids[pos + 1]
            backend.update_tile_order(ids)

        with reactive.isolate():
            layout_version.set(layout_version() + 1)

    @reactive.effect
    def _tile_order():
        ids = req(input.tile_order())  # list[str] pushed on html5 drag drop
        with reactive.isolate():
            if not can_edit():
                ui.notification_show(tr("Only a KpiTen manager can edit tiles."))
                return
            backend_rv().update_tile_order([int(i) for i in ids])
            layout_version.set(layout_version() + 1)
            ui.notification_show(tr("Tiles order saved."))

    # ---- drill-down : a click on a row of a table shows the rows behind it -------
    drill_keys: dict[int, list[dict]] = {}  # tile id -> the hidden key of each row

    @reactive.effect
    def _drill():
        click = req(input.drill_click())  # {line, row} from DRILL_JS
        with reactive.isolate():
            line_id, row = int(click["line"]), int(click["row"])
            line = next((l for l in lines() if l["id"] == line_id), None)
            keys = drill_keys.get(line_id) or []
            if line is None or not line.get("drill") or not 0 <= row < len(keys):
                return
            try:
                result = core_tiles.exec_drill(
                    line, line["model"], tile_store(line), predicates(), keys[row]
                )
            except Exception as err:
                logger.exception("drill-down of tile %s failed", line["name"])
                ui.notification_show(
                    tr("Drill-down failed : {error}", error=err), type="error"
                )
                return
            palette = current_theme().palette
            note = result.note_in(tr)
            note = (
                f'<div style="font-size: 11px; opacity: .65">{note}</div>'
                if note
                else ""
            )
            body = themes.gt_df(current_theme(), result.df).as_raw_html()
            ui.modal_show(
                ui.modal(
                    ui.HTML(
                        f'<div style="background: {palette["surface_hex"]}; padding: 8px; max-height: 70vh; overflow: auto">'
                        f"{body}{note}</div>"
                    ),
                    title=result.label,
                    easy_close=True,
                    size="xl",
                    footer=None,
                )
            )

    # ---- ask a KPI in words (kpiten_core.querychat) : for every user ------------
    # the model of `.env` ; `kt.config` may turn the AI off for everyone
    provider = llm.default_provider()
    ai_on = provider is not None and core_config.ai_enabled()
    ai_filters = reactive.Value({})  # tile id -> {"where", "title"}, this session only
    ai_line = reactive.Value(None)  # the tile the chat is about
    ai_history: dict[int, list] = {}  # tile id -> the conversation the model saw
    ai_log: dict[int, list] = {}  # tile id -> the messages shown
    ai_tables: dict[tuple, tuple] = {}  # (db, table, level) -> (description, anon)
    chat = ui.Chat("ai_chat", history=False) if provider is not None else None

    def tile_store(line: dict, store_data: dict | None = None) -> dict:
        """The store a tile reads : its table narrowed by the filter the AI made."""
        store_data = store() if store_data is None else store_data
        where = ai_filters().get(line["id"])
        if not where or line["model"] not in store_data:
            return store_data
        frame = querychat.apply(store_data[line["model"]].lazy(), where["where"])
        return {**store_data, line["model"]: frame}

    def ai_about() -> str:
        """What the model is, and what it is told of a table (`kt.config`)."""
        told = {
            "schema": "It is told the names and types of the columns only.",
            "clear": "It is told the columns, figures on them and a few rows, in clear.",
        }.get(
            core_config.ai_send_level(),
            "It is told the columns, figures on them and a few rows, with pseudonyms "
            "for the people and the products.",
        )
        text = tr("Model : {model}.", model=provider.label) + " " + tr(told)
        if not provider.leaves_machine:
            text += " " + tr("Nothing leaves the machine.")
        return text

    @render.ui
    def ai_head():
        if provider is None:
            return None
        if not ai_on:  # turned off in `kt.config` : no chat, no ✨
            return ui.tags.style(
                ".kpiten-ai-layout > .sidebar, .kpiten-ai-layout > "
                ".collapse-toggle { display: none !important }"
            )
        line = ai_line()
        title = f"« {line['name']} »" if line else tr("Ask a KPI")
        return ui.div(
            ui.HTML(svg("wand-magic-sparkles")),
            ui.span(title),
            ui.span(ui.HTML(svg("circle-info")), class_="tile-info", title=ai_about()),
            class_="kpiten-ai-head",
        )

    async def ai_say(line_id: int | None, role: str, text: str) -> None:
        if line_id is not None:
            ai_log.setdefault(line_id, []).append({"role": role, "content": text})
        await chat.append_message({"role": role, "content": text})

    @reactive.effect
    @reactive.event(input.ai_tile)
    async def _ai_open():
        """✨ on a tile : the chat is about it, with what was said of it before."""
        line = next((l for l in lines() if l["id"] == input.ai_tile()), None)
        if line is None or not ai_on:
            return
        ai_line.set(line)
        ui.update_sidebar("ai_sidebar", show=True)
        await chat.clear_messages()
        for message in ai_log.get(line["id"], []):
            await chat.append_message(message)
        if not ai_log.get(line["id"]):
            await ai_say(
                line["id"],
                "assistant",
                tr(
                    "Which rows should « {name} » count ? For example « only the "
                    "confirmed orders ». « Remove the filter » gives the whole KPI "
                    "back.",
                    name=line["name"],
                )
                + "\n\n"
                + tr(
                    "The filter only changes this tile, for you ; it is lost when "
                    "the page is reloaded."
                ),
            )

    @reactive.effect
    @reactive.event(input.ai_clear)
    async def _ai_clear():
        """× on the badge of a tile : the whole tile again."""
        line_id = input.ai_clear()
        filters = dict(ai_filters())
        if filters.pop(line_id, None) is None:
            return
        ai_filters.set(filters)
        line = ai_line()
        if line is not None and line["id"] == line_id:
            await ai_say(
                line_id,
                "assistant",
                tr("Filter removed : the KPI counts all its rows again."),
            )

    if chat is not None:

        @chat.on_user_submit
        async def _ai_ask(question: str):
            line = ai_line()
            if line is None or not ai_on:
                await chat.append_message(tr("Click ✨ on a tile first."))
                return
            ai_log.setdefault(line["id"], []).append(
                {"role": "user", "content": question}
            )
            backend, table = backend_rv(), line["model"]
            frame = store().get(table)
            if frame is None:
                await ai_say(line["id"], "assistant", f"{table} ?")
                return
            level = core_config.ai_send_level()
            key = (backend.db, table, level)
            history = ai_history.get(line["id"], [])

            def work() -> querychat.Reply:
                # the figures on the table and the model : off the event loop
                if key not in ai_tables:
                    anon = anonymize.for_table(backend, table, hide=level != "clear")
                    ai_tables[key] = (anonymize.summary(frame, anon, level), anon)
                description, anon = ai_tables[key]
                return querychat.ask(
                    provider,
                    line,
                    frame,
                    description,
                    history,
                    question,
                    anon,
                    lang=odoo_lang or "",
                )

            logger.info("ai : %s asks %r on tile %s", backend.db, question, line["id"])
            reply = await asyncio.to_thread(work)
            logger.info("ai : %s %r %s", reply.action, reply.where, reply.error or "")
            ai_history[line["id"]] = (history + reply.exchange)[
                -2 * querychat.HISTORY :
            ]
            text = reply.text
            filters = dict(ai_filters())
            if reply.action == querychat.FILTER:
                filters[line["id"]] = {"where": reply.where, "title": reply.title}
                text += f"\n\n```sql\n{reply.where}\n```"
            elif reply.action == querychat.CLEAR:
                filters.pop(line["id"], None)
            if filters != ai_filters():
                ai_filters.set(filters)
            await ai_say(line["id"], "assistant", text)

    def panel_results() -> list:
        """(line, result, error) per tile of the panel : computed with its period, its
        filters and the rights of the user (the tiles on screen, the exports)."""
        store_data = store()
        predicate_list = predicates()
        previous_predicates, previous_label = previous()
        field_labels = core_labels.field_labels_of(backend_rv(), odoo_lang)
        logger.info("predicates : %s", [str(p) for p in predicate_list])
        results = []
        for line in lines():
            try:
                result = core_tiles.exec_tile(
                    line,
                    line["model"],
                    tile_store(line, store_data),
                    predicate_list,
                    previous_predicates,
                    previous_label,
                    field_labels,
                )
                results.append((line, result, None))
            except Exception as err:
                logger.exception("tile %s failed", line["name"])
                results.append((line, None, str(err)))
        return results

    # ---- the exports of the panel the plugins offer (kpiten_core.hookspecs)
    exports = core_plugins.panel_exports()

    @render.ui
    def plugin_exports():
        return ui.TagList(
            *(
                ui.download_button(
                    f"export_{export['key']}",
                    ui.HTML(export.get("icon") or export["label"]),
                    class_="btn-kpiten",
                    title=export.get("tooltip") or export["label"],
                )
                for export in exports
            )
        )

    def export_download(export: dict):
        """The download of an export : the plugin makes the file of the panel."""

        def filename() -> str:
            name = panels().get(str(input.panel())) or "panel"
            slug = re.sub(r"[^\w-]+", "-", name).strip("-").lower()
            return f"kpiten-{slug}-{datetime.date.today()}.{export['extension']}"

        def download():
            with reactive.isolate():
                panel_id = int(req(input.panel()))
                backend = backend_rv()
                user_id = current_user_id()
                context = {
                    "filters": filters_text(),
                    "user": backend.get_user_name(user_id),
                    "db": backend.db,
                    "palette": current_theme().palette,
                    "date": datetime.date.today(),
                }
                panel = {"id": panel_id, "name": panels().get(str(panel_id))}
                data = core_plugins.export_panel(
                    export["key"], panel, panel_results(), context
                )
            yield data

        download.__name__ = f"export_{export['key']}"  # the id of its button
        return render.download(filename=filename, media_type=export["media_type"])(
            download
        )

    for export in exports:
        export_download(export)

    # ---- the trend under a card : its model's documents per month, over the period
    def sparkline(line: dict, color: str) -> str:
        config = panel_settings().get("filter_config") or {}
        frame = store().get(line["model"])
        if frame is None:
            return ""
        columns = frame.collect_schema()
        date = next((f for f in filterstate.date_fields(config) if f in columns), None)
        if date is None:
            return ""
        try:
            # the core leaves out a filter on a column this model does not have
            rows = (
                core_tiles.filter_df(frame.lazy(), predicates())
                .group_by(pl.col(date).dt.truncate("1mo").alias("month"))
                .agg(pl.len().alias("n"))
                .sort("month")
                .collect()
            )
        except Exception:  # a predicate on a column this model does not have
            return ""
        if rows.height < 2:
            return ""
        fig = go.Figure(
            go.Scatter(
                x=rows["month"],
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
        fig.update_layout(
            showlegend=False,
            height=34,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig.to_html(
            include_plotlyjs=False,
            full_html=False,
            config={"displayModeBar": False, "staticPlot": True},
        )

    # ---- the interactive grids : a `grid_<id>` output per tile that asks for it
    grid_frames: dict[int, pl.DataFrame] = {}
    grid_heights: dict[int, str] = {}  # the height of the tile, less its title
    grid_version = reactive.Value(0)
    grids: set[int] = set()

    def grid_output(tile_id: int) -> None:
        if tile_id in grids:
            return
        grids.add(tile_id)

        def grid():
            grid_version()
            frame = grid_frames.get(tile_id)
            if frame is None:
                return None
            return render.DataGrid(frame, filters=True, height=grid_heights[tile_id])

        grid.__name__ = f"grid_{tile_id}"
        render.data_frame(grid)

    @render.ui
    def tiles():
        panels()  # ensure the select is populated
        req(input.panel())  # no rendering before a panel is selected
        theme = current_theme()
        tile_lines = lines()
        try:  # the switch is only there for a manager, and after its first render
            edit_mode_on = can_edit() and bool(input.edit_mode())
        except SilentException:
            edit_mode_on = False
        cards, blocks = [], []
        drill_keys.clear()
        for line, result, error in panel_results():
            try:
                if error is not None:
                    raise core_tiles.TileError(error)
                if result.keys:
                    drill_keys[line["id"]] = result.keys
                # None unless the feature is on and the rows are records of the model
                records = core_tiles.records_link(backend_rv(), line["model"], result)
                grid = (
                    line.get("table_view") == "grid"
                    and result.df is not None
                    and not edit_mode_on
                )
                if grid:
                    grid_output(line["id"])
                    grid_frames[line["id"]] = grid_rows(result.df)
                    height = max((line.get("tile_height") or 260) - 60, 200)
                    grid_heights[line["id"]] = f"{height}px"
                trend = (
                    sparkline(line, card_icon(line["name"])[1])
                    if result.kind == "card" and not edit_mode_on
                    else ""
                )
                rendered = (
                    tile_edit_item(line, theme, result, records)
                    if edit_mode_on
                    else tile_html(
                        line,
                        theme,
                        result,
                        tile_info(line),
                        records,
                        sparkline=trend,
                        grid=grid,
                        tr=tr,
                        ai=ai_html(ai_filters().get(line["id"]), tr) if ai_on else "",
                    )
                )
            except Exception as err:
                logger.exception("tile %s failed", line["name"])
                rendered = (
                    tile_error_item_html(line, err)
                    if edit_mode_on
                    else tile_error_html(line, str(err), tile_info(line))
                )
            # cards have a fixed height : their own grid section, right
            # below the filters and above the other kpis
            (cards if line["kind"] == "card" else blocks).append(rendered)
        with reactive.isolate():
            grid_version.set(grid_version() + 1)  # the grids read their new rows
        html_cards = "".join(cards)
        html_blocks = "".join(blocks)
        TILES_DUMP.write_text(html_cards + html_blocks)
        logger.info("rendered %s/%s tiles", len(cards) + len(blocks), len(tile_lines))
        classes = "tile-grid tile-grid--edit" if edit_mode_on else "tile-grid"
        card_classes = classes + " card-grid"
        parts = [
            ui.tags.div(ui.HTML(html_cards), class_=card_classes) if cards else None,
            ui.tags.div(ui.HTML(html_blocks), class_=classes) if blocks else None,
        ]
        return ui.tags.div(
            [p for p in parts if p is not None]
            + ([ui.tags.script(EDIT_MODE_JS)] if edit_mode_on else [])
            # the script of the data grids : their outputs are in the html of the
            # tiles (a string), which does not bring it
            + list(GRID_DEPENDENCIES)
        )


app = App(
    app_ui,
    server,
    static_assets={"/static": STATIC_DIR},
)
