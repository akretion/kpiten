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

from kpiten_core import brand, comparison, links
from kpiten_core import config as core_config
from kpiten_core import ods as core_ods
from kpiten_core import plugins as core_plugins
from kpiten_core.render.gtable import DRILL_CSS
from kpiten_core.render.plotly import _with_alpha, apply_theme_colors
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
FAVICON = ui.tags.link(rel="icon", type="image/png", href="static/favicon.png")

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


def app_ui(req):  # noqa: ANN001
    from kpiten_core import env

    if not env.allow_rpc_user and not SessionHandler.get(
        req.cookies.get(SESSION_COOKIE)
    ):
        return ui.page_fluid(
            {"class": "kpiten-dashboard"},
            ui.head_content(FAVICON),
            ui.h3("Not connected"),
            ui.p("Open the dashboard from Odoo : menu KpiTen → Dashboard."),
            title=f"Not connected · {TAB_TITLE}",
        )
    logo = "static/logo.png"  # relative : works at app root and under /dashboard
    return ui.page_fluid(
        {"class": "kpiten-dashboard"},
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
                # the logo of KpiTen, and its slogan on hover
                ui.div(
                    ui.tags.img(
                        src="static/kpiten.png",
                        alt=brand.NAME,
                        class_="kpiten-logo",
                        title=brand.tooltip(),
                    ),
                    ui.span(brand.NAME),
                    class_="kpiten-brand",
                ),
                ui.input_select("panel", "Panel", choices=[], width="100%"),
                ui.output_ui("filters"),
                ui.output_ui("theme_select"),
                ui.output_ui("db_select"),
                ui.tags.span(
                    ui.input_switch("edit_mode", "Edit", False), title=EDIT_TOOLTIP
                ),
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
                    title=REFRESH_TOOLTIP,
                ),
                ui.output_ui("ods_button"),
                # the exports of the panel the plugins offer (quarto-kpiten : a PDF)
                ui.output_ui("plugin_exports"),
                ui.output_ui("data_freshness"),
                # the logo of the framework, on the right
                ui.tags.a(
                    ui.tags.img(src=logo, class_="framework-logo"),
                    href="https://shiny.posit.co",
                    title="Made with Shiny",
                    target="_blank",
                    class_="framework-side",
                ),
                class_="top-bar",
            ),
            ui.div(ui.output_ui("tiles")),
            # the logo with its name at the end of the page, on the right
            ui.div(
                ui.HTML(brand.lockup_svg(64)),
                class_="app-footer",
                title=brand.tooltip(),
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


def tile_header(line: dict, kind: str, info: str) -> str:
    """The title of a tile : its icon, its name, its kind ; the filters it was
    computed with (an info icon) and the full screen button on the right."""
    info_icon = (
        f'<span class="tile-info" title="{info}">{svg("circle-info")}</span>'
        if info
        else ""
    )
    return (
        f'<h3><span class="tile-icon">{svg(TILE_ICONS.get(kind, "table-list"))}</span>'
        f'<span class="tile-name">{line["name"] or kind}</span>'
        f'<span class="kind-badge">{kind}</span>'
        f'<span class="tile-actions">{info_icon}'
        f'<button type="button" class="tile-full" title="Full screen (Esc to leave)">'
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


def _inject_toolbar(content: str, line: dict) -> str:
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
        f'<button class="tile-act" data-action="{key}" title="{label}" '
        f'aria-label="{label}">{icon}</button>'
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


# ---- tiles html rendering ---------------------------------------------
def records_link_html(records: dict | None) -> str:
    """The link under a table that lists Odoo records : the same list, in Odoo (the
    rights of the user apply there). `records` is `core_tiles.records_link`."""
    if not records:
        return ""
    count, total = records["count"], records["total"]
    label = (
        f"Open these {count} records in Odoo"
        if count == total
        else f"Open the first {count} of {total} records in Odoo"
    )
    return (
        f'<a class="records-link" href="{html_escape(records["url"], quote=True)}" '
        'target="_blank" rel="noopener noreferrer" '
        'title="The same list of records, in Odoo (with your rights)">'
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
) -> str:
    """Tile html ; `info` goes in a tooltip = active filters description ; `records` is
    the link that opens the listed records in Odoo (when the KPI lists some) ;
    `sparkline` the trend under a card's value ; `grid` : a table drawn as an
    interactive grid (`grid_<id>`, the server renders it)."""
    p = theme.palette
    tooltip = f' title="{info}"' if info else ""
    if result.kind == "card":
        # odoo-dashboard style kpi : compact single value, no big title
        return (
            f'<div class="tile kpi-card" data-tile-id="{line["id"]}"{tooltip}>'
            f'<div class="kpi-head">{card_badge(line["name"])}'
            f'<span class="kpi-label">{line["name"] or ""}</span></div>'
            # a name (best seller...) is text : smaller, it can be long
            f'<div class="value{" kpi-text" if isinstance(result.value, str) else ""}">'
            f"{html_escape(result.text)}</div>"
            + (
                f'<div class="kpi-sub">{html_escape(result.subtitle)}</div>'
                if result.subtitle
                else ""
            )
            + (comparison.html_block(result.comparison, p) if result.comparison else "")
            + (f'<div class="kpi-trend">{sparkline}</div>' if sparkline else "")
            + "</div>"
        )
    parts = [tile_header(line, result.kind, info)]
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
        parts.append(result.figure.to_html(include_plotlyjs=False, full_html=False))
    elif grid and result.df is not None:
        # sorted and filtered by the user : the server renders `grid_<id>`
        parts.append(str(ui.output_data_frame(f"grid_{line['id']}")))
    else:
        assert result.df is not None
        # the rows of `kt.config` shown : the tile scrolls, the page does not grow
        rows = core_config.table_rows()
        parts.append(themes.gt_df(theme, result.df.head(rows)).as_raw_html())
        # out of what the tile holds (`total_rows` when the core already cut it off)
        total = result.meta.get("total_rows", result.df.height)
        if total > rows:
            result.meta["note"] = f"First {rows} of {total:,} rows".replace(",", " ")
    if result.note:
        # the tile was reduced to stay renderable (see kpiten_core.tiles)
        parts.append(
            f'<div style="font-size: 11px; opacity: .65; margin-top: 4px">'
            f"{result.note}</div>"
        )
    parts.append(records_link_html(records))
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

    def current_user_id() -> int:
        """Odoo user of this session (dev mode : the rpc login user)."""
        return sso.user_id if sso else backend_rv().env.user.id

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
                detail=f"{kind} : {model} — {totals[model]} records",
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
            ui.notification_show(f"Database switched to {db}")

    @render.ui
    def db_select():
        """Odoo database selector (each db has its own parquet snapshot)."""
        try:
            databases = [sso.db] if sso else backend_rv().list_databases()
        except Exception:
            databases = [backend_rv().db]
        return ui.input_select(
            "db",
            "Database",
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
            "Theme",
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
            title="Data as of "
            + stamp
            + " — parquet snapshot time ; \u27f3 syncs with Odoo",
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
                    "Period",
                    choices=options,
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
        return filterstate.describe_filters(config, date_value, dim_values)

    # ---- the raw rows of an Odoo model as a spreadsheet, with the user's rights
    @render.ui
    def ods_button():
        """The export is for who `kt.config` says (everyone, the managers, nobody)."""
        if not core_config.explore_allowed(can_edit()):
            return None
        return ui.input_action_button(
            "ods_open", "\u2913", class_="btn-kpiten", title=ODS_TOOLTIP
        )

    @reactive.effect
    @reactive.event(input.ods_open)
    def _ods_dialog():
        models = core_ods.exportable_models(store())
        ui.modal_show(
            ui.modal(
                ui.input_select("ods_model", None, models, width="100%"),
                title="Download the rows of a model",
                easy_close=True,
                size="s",
                footer=ui.download_button(
                    "ods",
                    ui.HTML(SPREADSHEET_ICON),
                    class_="btn-kpiten",
                    title=ODS_MODEL_TOOLTIP,
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
                raise PermissionError("You may not export the rows.")
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
                    more = f"Tile: {where}"
                    info = info + "\n" + more if info else more
            except Exception:
                pass
        return info.replace('"', "'")

    def tile_edit_item(
        line: dict,
        theme: themes.Theme,
        result: core_tiles.TileResult,
        records: dict | None = None,
    ) -> str:
        """Same CSS-grid tile, draggable with an edit toolbar."""
        content = _inject_toolbar(
            tile_html(line, theme, result, tile_info(line), records), line
        )
        return (
            f'<div class="tile-edit-item" data-tile-id="{line["id"]}"'
            f' draggable="true" style="grid-column: span {span_of(line)}">{content}</div>'
        )

    def tile_error_item_html(line: dict, error: str) -> str:
        content = _inject_toolbar(
            tile_error_html(line, str(error), tile_info(line)), line
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
            ui.notification_show("Data synced with Odoo.", duration=3)

    # ---- edit mode : layout save + tile delete -------------------------
    @reactive.effect
    def _tile_action():
        act = req(input.tile_action())  # dict {id, action} from EDIT_MODE_JS
        tile_id, action = int(act["id"]), act["action"]
        backend = backend_rv()
        with reactive.isolate():
            if not can_edit():
                ui.notification_show("Only a KpiTen manager can edit tiles.")
                return

        with reactive.isolate():
            cur_lines = lines()
        by_id = {line["id"]: line for line in cur_lines}
        line = by_id.get(tile_id)
        if line is None:
            return

        if action == "delete":
            backend.delete_tile(tile_id)
            ui.notification_show(f"Tile #{tile_id} deleted")

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
                ui.notification_show("Only a KpiTen manager can edit tiles.")
                return
            backend_rv().update_tile_order([int(i) for i in ids])
            layout_version.set(layout_version() + 1)
            ui.notification_show("Tiles order saved.")

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
                    line, line["model"], store(), predicates(), keys[row]
                )
            except Exception as err:
                logger.exception("drill-down of tile %s failed", line["name"])
                ui.notification_show(f"Drill-down failed : {err}", type="error")
                return
            palette = current_theme().palette
            note = (
                f'<div style="font-size: 11px; opacity: .65">{result.note}</div>'
                if result.note
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

    def panel_results() -> list:
        """(line, result, error) per tile of the panel : computed with its period, its
        filters and the rights of the user (the tiles on screen, the exports)."""
        store_data = store()
        predicate_list = predicates()
        previous_predicates, previous_label = previous()
        logger.info("predicates : %s", [str(p) for p in predicate_list])
        results = []
        for line in lines():
            try:
                result = core_tiles.exec_tile(
                    line,
                    line["model"],
                    store_data,
                    predicate_list,
                    previous_predicates,
                    previous_label,
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
                    "user": backend.env["res.users"].browse(user_id).name,
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
