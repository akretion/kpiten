"""Simplified NiceGUI dashboard on top of kpiten-core.

Same core pieces as the shiny app (kpiten_core tiles/filters/loaders)
with a minimal NiceGUI UI :

- panel select, period + dimension filters (panel.filter_config)
- 3-column CSS grid of dark tiles (card / graph / pivot / union / data)
- tile refresh, parquet refresh
- 2 simple css-var themes (initial via `?theme=` query param, selected
  value stays in browser storage)

No SSO and no edit mode (that's the "simplified" part of the port).
"""

import logging
import pathlib

from kpiten_core.gtable import gt_table
from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui, run

from kpiten_core import filters
from kpiten_core import comparison, links
from kpiten_core import tiles as core_tiles
from kpiten_core.backend import Backend
from kpiten_core.loaders import (
    last_sync,
    user_store,
)
from kpiten_core.service import service as kpiten_service

from .sessions import SESSION_COOKIE, SessionHandler

STATIC_DIR = str(pathlib.Path(__file__).parent / "static")
app.add_static_files("/static", STATIC_DIR)

logger = logging.getLogger(__name__)

THEMES = {
    "akretion": {
        "name": "Akretion",
        "theme": "dark",
        "gradient": "linear-gradient(135deg, #101226 0%, #0b1f3b 45%, #0a3f6b 130%)",
        "accent": "#00dc82",
        "surface": "rgba(9, 12, 28, .85)",
        "text": "#dbe4ef",
        "border": "rgba(0, 220, 130, .25)",
        "thead": "#081225",
        "surface_hex": "#101226",
        "border_hex": "rgba(0,220,130,.25)",
        "row_line": "rgba(255,255,255,.06)",
    },
    "midnight": {
        "name": "Midnight",
        "theme": "dark",
        "gradient": "linear-gradient(160deg, #0e1231 0%, #142452 45%, #0047e1 130%)",
        "accent": "#34cdfe",
        "surface": "rgba(14, 18, 49, .8)",
        "text": "#e8ecf8",
        "border": "rgba(52, 205, 254, .25)",
        "thead": "#0b1030",
        "surface_hex": "#0e1231",
        "border_hex": "rgba(52,205,254,.25)",
        "row_line": "rgba(52,205,254,.12)",
    },
    "light": {
        "name": "Sand",
        "theme": "light",
        "gradient": "linear-gradient(180deg, #faf6ef 0%, #f3ecdd 45%, #e9dfc9 130%)",
        "accent": "#a06b2a",
        "surface": "rgba(255, 253, 249, .94)",
        "text": "#4a4238",
        "border": "rgba(160, 107, 42, .25)",
        "thead": "#f1e9d9",
        "surface_hex": "#fffdf9",
        "border_hex": "rgba(160,107,42,.25)",
        "row_line": "rgba(74, 66, 56, .07)",
    },
}
DEFAULT_THEME = "akretion"

CSS = """
.bb-ktd {
  --accent: #00dc82;
  --surface: rgba(9, 12, 28, .85);
  --text: #dbe4ef;
  --border: rgba(0, 220, 130, .25);
  --thead: #081225;
  --gradient: linear-gradient(135deg, #101226 0%, #0b1f3b 45%, #0a3f6b 130%);
  color: var(--text);
  background: var(--gradient) fixed;
  min-height: 100vh;
}
.framework-logo { width: 76px; height: auto; border-radius: 6px }
.bb-ktd .q-field--dark .q-field__control,
.bb-ktd .q-field--dark .q-field__native,
.bb-ktd .q-field--dark .q-field__label,
.bb-ktd .q-field--dark .q-field__append {
  color: var(--text) !important;
}
.bb-ktd .q-field--dark .q-field__control { background: rgba(255,255,255,.06); }
/* sand theme : lighten the quasar dark-styled controls */
.bb-ktd-light .q-field--dark .q-field__control,
.bb-ktd-light .q-field--dark .q-field__native,
.bb-ktd-light .q-field--dark .q-field__label,
.bb-ktd-light .q-field--dark .q-field__append {
  color: #4a4238 !important;
}
.bb-ktd-light .q-field--dark .q-field__control {
  background: rgba(74, 66, 56, .07) !important;
}
.bb-ktd-light .q-field--dark .q-field__native .q-select__dropdown-icon,
.bb-ktd-light .q-field--dark .q-field__marginal {
  color: #4a4238 !important;
}
.bb-ktd-light .bb-menu-dark { background: #fffdf9; color: #4a4238 }
.bb-ktd-light .bb-menu-dark .q-item { color: #4a4238 }
.bb-ktd-light .q-switch__inner { color: #4a4238 }
.bb-ktd-light .q-btn { color: #4a4238 }
.tile-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
/* cards row : odoo-dashboard style kpi line — one compact centered row of
   single-value tiles, each sized to its content */
.card-grid {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}
.card-grid .tile {
  width: auto;
  min-width: 160px;
  max-width: 280px;
  flex: 0 1 auto;
  max-height: 86px;
  min-height: 86px;
  justify-content: center;
  gap: 2px;
  overflow: hidden;
}
.card-grid .tile .kpi-label {
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-grid .tile .text-3xl { font-size: 1.9rem !important; line-height: 1.1 }
.tile a[href] { color: var(--link-color, inherit); }
.tile {
  max-height: 460px;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 8px 12px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 24px rgba(0, 0, 0, .25);
}
.tile h3 {
  margin: 0 0 8px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--accent);
}
.tile .gt { font-size: 13px; max-height: 320px; overflow: auto }
"""


def theme_style(palette: dict) -> str:
    """CSS vars of the theme, applied server-side (no js dependency)."""
    return (
        f"--accent: {palette['accent']};"
        f"--surface: {palette['surface']};"
        f"--text: {palette['text']};"
        f"--border: {palette['border']};"
        f"--thead: {palette['thead']};"
        f"--gradient: {palette['gradient']}"
    )


EDIT_CSS = """
.tile-edit-item { border-style: dashed; cursor: grab }
.tile-tools { gap: 2px !important; margin-bottom: 6px }
.tile-tools .q-btn { color: var(--text) }
.tile-tools .q-btn:hover { color: var(--accent) }
.tile-edit-item[data-tile-id] { position: relative }
.tile-grid--edit .tile-edit-item { min-height: 120px }
"""

EDIT_JS = """
(function () {
  document.querySelectorAll('.tile-grid').forEach(function (grid) {
    if (grid.dataset.kpitenEdit) { return; }
    grid.dataset.kpitenEdit = '1';
    grid.addEventListener('dragstart', function (e) {
      const item = e.target.closest('.tile-edit-item');
      if (!item) { return; }
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', item.dataset.tileId);
    });
    grid.addEventListener('dragover', function (e) { e.preventDefault(); });
    grid.addEventListener('drop', function (e) {
      e.preventDefault();
      const src = e.dataTransfer.getData('text');
      const dropEl = e.target.closest('.tile-edit-item');
      const dragEl = grid.querySelector('[data-tile-id="' + src + '"]');
      if (!src || !dropEl || !dragEl || dropEl === dragEl) { return; }
      grid.insertBefore(dragEl, dropEl);
      const ids = Array.from(grid.querySelectorAll('.tile-edit-item'))
          .map(function (i) { return i.dataset.tileId; });
      // emitEvent can't reach ui.on in nicegui 3.x : post the ids instead
      fetch('/kpiten/tile-order', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: ids}),
      });
    });
  });
})();
"""


def tile_view(
    line: dict,
    result: core_tiles.TileResult,
    palette: dict,
    edit: bool = False,
    act=None,
    info: str = "",
):
    """Draw one tile inside its card container (with toolbar in edit mode)."""
    container_context = ui.element if edit else ui.column
    container = container_context().classes("tile")
    if edit:
        container.classes("tile-edit-item", replace=False)
        container.props(f'data-tile-id="{line["id"]}" draggable')
    if info:
        # tooltip = active panel filters («how was this data filtered »)
        container.tooltip(info)
    with container:
        if edit and act is not None:
            edit_toolbar(line, act)
        if result.kind == "card":
            # odoo-dashboard style kpi : compact single value, no big title
            container.classes("kpi-card")
            ui.label(line["name"] or "").classes("kpi-label text-xs")
            # a name (best seller...) is text : smaller, it can be long
            big = "text-base" if isinstance(result.value, str) else "text-3xl"
            ui.label(result.text).classes(f"{big} font-bold ellipsis").style(
                "max-width: 250px"
            )
            if result.subtitle:
                ui.label(result.subtitle).classes("text-xs opacity-70")
            if result.comparison:
                # variation against the period before, like an Odoo scorecard
                delta = result.comparison
                color = comparison.color(delta)
                with ui.row().classes("items-baseline gap-1 text-xs"):
                    ui.label(comparison.label(delta)).classes("font-semibold").style(
                        f"color: {color}" if color else ""
                    ).tooltip(comparison.tooltip(delta))
                    ui.label(delta["description"]).classes("opacity-60")
            return
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.label(line["name"] or result.kind).classes("text-base font-semibold")
            ui.badge(result.kind, color="transparent").props(
                f'outline style="color:{palette["accent"]}"'
            )
        if result.kind == "graph":
            ui.plotly(result.figure).classes("w-full")
        else:
            assert result.df is not None
            # setHTML drops the `style` of the links : their color comes from here
            ui.html(gt_table(result.df.head(20), palette).as_raw_html()).style(
                f"--link-color: {palette['accent']}"
            )
        note = result.note
        if result.df is not None:
            # 20 rows shown, out of what the tile holds (`total_rows` when the
            # core already cut it off)
            total = result.meta.get("total_rows", result.df.height)
            if total > 20:
                note = f"First 20 of {total:,} rows".replace(",", " ")
        if note:
            ui.label(note).classes("text-xs opacity-60")


def edit_toolbar(line: dict, act):
    """Tile editing toolbar (move / width / height / delete) -> Odoo autosave."""
    actions = [
        ("left", "chevron_left", "Move left"),
        ("right", "chevron_right", "Move right"),
        ("hinc", "unfold_more", "Taller"),
        ("hdec", "unfold_less", "Shorter"),
        ("winc", "add_box", "Wider"),
        ("wdec", "indeterminate_check_box", "Narrower"),
        ("delete", "delete", "Delete"),
    ]
    with ui.row().classes("tile-tools w-full gap-1"):
        ui.label(f"#{line['id']}").classes("text-xs opacity-60")
        for action, icon, tooltip in actions:
            ui.button(
                icon=icon,
                on_click=lambda _, tid=line["id"], action=action: act(tid, action),
            ).props("dense flat size=sm").tooltip(tooltip).classes("tile-act")


def error_view(line: dict, error: str, info: str = ""):
    tile = ui.column().classes("tile")
    if info:
        tile.tooltip(info)
    with tile:
        ui.label(line.get("name") or "").classes("text-base font-semibold")
        ui.label(str(error)[:200]).classes("text-sm text-red-400")


@ui.page("/")
def dashboard(request: Request, theme: str = DEFAULT_THEME, db: str | None = None):
    ui.add_head_html(f"<style>{CSS}{links.LINK_CSS}</style>")
    ui.add_head_html(f"<script>{links.NEW_TAB_JS}</script>")
    from kpiten_core import env

    # who is connected : the SSO session of this browser (cookie), nothing is
    # shared with the other users. Only the dev mode (ALLOW_RPC_USER) runs
    # without one, as the rpc login user (and may pick the db in the url).
    sso = SessionHandler.get(request.cookies.get(SESSION_COOKIE))
    if sso is None and not env.allow_rpc_user:
        ui.label("Not connected").classes("text-xl")
        ui.label("Open the dashboard from Odoo : menu KpiTen → Dashboard.")
        return
    backend = Backend.create(db=sso.db if sso else db)
    env.current_db = backend.db
    # Apply the odoo-side chart defaults (colors) once per page load.
    core_tiles.set_chart_config(backend.get_chart_config())
    links.set_odoo_url(backend.get_base_url())
    panels = backend.get_panels()
    if not panels:
        ui.label("No kpiten.panel found in Odoo").classes("text-xl")
        return
    panels_map = {str(p["id"]): p["name"] for p in panels}
    user_id = sso.user_id if sso else backend.env.user.id
    # only a KpiTen manager of Odoo edits the tiles (the apps read Odoo with one
    # rpc account : nothing else stops a user from sending an edit)
    can_edit = backend.can_edit_tiles(user_id)
    # default panel : first one in sequence order (get_panels is sorted)
    state_panel = panels[0]["id"] if panels else None
    if state_panel is None:
        ui.label("No panel found in Odoo").classes("text-lg")
        return
    try:
        # an SSO user is bound to the database of the session
        databases = [sso.db] if sso else backend.list_databases() or [backend.db]
    except Exception:
        databases = [backend.db]
    filt = {"date": filters.DEFAULT_DATE_OPTION, "dims": {}}
    theme_key = theme if theme in THEMES else DEFAULT_THEME
    app.storage.browser["theme"] = theme_key

    store_cache = user_store(backend, user_id)
    if not store_cache:
        # fresh database : ask kpiten-core for a full connectorx extract
        kpiten_service.request_refresh(backend.db)
        store_cache = user_store(backend, user_id)

    panel_label = {"id": state_panel}

    def get_config() -> dict:
        return backend.get_panel_settings(panel_label["id"]).get("filter_config") or {}

    def on_panel_change(e):
        panel_label["id"] = int(e.value)
        filt.update(date=None, dims={})  # draw_filters picks the period of the panel
        draw_filters()
        # Data (store_cache) is independent of the panel : just redraw the
        # tiles of the selected panel, no need to sync again with Odoo.
        draw_tiles()

    def draw_filters():
        filters_row.clear()
        config = get_config()
        with filters_row:
            if config.get("date"):
                # the choices fit the data of the panel : windows, months or years it covers
                span = filters.date_range(store_cache, config)
                options = filters.date_options(span)
                if filt["date"] not in options:
                    filt["date"] = filters.default_date_option(options, span)
                ui.select(
                    options=options,
                    value=filt["date"],
                    on_change=lambda e: filt.update(date=e.value) or draw_tiles(),
                    label="Period",
                ).props("dark dense outlined").props(
                    'popup-content-class="bb-menu-dark"'
                ).classes(
                    "w-40"
                )
            for dim in config.get("dimensions", []):
                choices = filters.dimension_choices(store_cache, dim["name"])
                ui.select(
                    options=choices,
                    value=filt["dims"].get(dim["name"], []),
                    on_change=lambda e, key=dim["name"]: (
                        filt["dims"].update({key: e.value}) or draw_tiles()
                    ),
                    label=dim.get("label") or dim["name"],
                    multiple=True,
                ).props("dark dense outlined clearable").props(
                    'popup-content-class="bb-menu-dark"'
                ).classes(
                    "w-64"
                )

    def draw_tiles():
        config = get_config()
        date_value = filters.bounds_of_option(filt["date"])
        predicates = filters.make_predicates(config, date_value, filt["dims"])
        previous_predicates = filters.make_previous_predicates(
            config, date_value, filt["dims"]
        )
        previous_label = filters.describe_previous(date_value)
        info = filters.describe_filters(config, date_value, filt["dims"])
        logger.info("predicates : %s", [str(p) for p in predicates])
        cards_grid.clear()
        tiles_grid.clear()
        with cards_grid, tiles_grid:
            for line in backend.get_panel_tiles(panel_label["id"], user_id):
                try:
                    result = core_tiles.exec_tile(
                        line,
                        line["model"],
                        store_cache,
                        predicates,
                        previous_predicates,
                        previous_label,
                    )
                    grid = cards_grid if line["kind"] == "card" else tiles_grid
                    with grid:
                        tile_view(
                            line,
                            result,
                            THEMES[theme_key],
                            edit=edit_state["on"],
                            act=act,
                            info=info,
                        )
                except Exception as err:
                    logger.exception("tile %s failed", line.get("name"))
                    with tiles_grid:
                        error_view(line, err, info)
        if edit_state["on"]:
            ui.add_head_html(f"<style>{EDIT_CSS}</style>")
            ui.run_javascript(EDIT_JS)

    def act(tile_id: int, action: str):
        """One edit action on a tile, saved in odoo right away."""
        if not can_edit:
            ui.notify("Only a KpiTen manager can edit tiles.", type="warning")
            return
        cur_lines = backend.get_panel_tiles(panel_label["id"], user_id)
        line = next((l for l in cur_lines if l["id"] == tile_id), None)
        if line is None:
            return
        if action == "delete":
            backend.delete_tile(tile_id)
            ui.notify(f"Tile #{tile_id} deleted")
        elif action in ("winc", "wdec", "hinc", "hdec"):
            col_span = line.get("col_span") or 1
            tile_height = line.get("tile_height") or 260
            if action == "winc":
                col_span = min(3, col_span + 1)
            elif action == "wdec":
                col_span = max(1, col_span - 1)
            elif action == "hinc":
                tile_height += 40
            else:
                tile_height = max(40, tile_height - 40)
            backend.update_tile_layout(tile_id, col_span, tile_height)
        else:  # left / right : swap then store the new sequence
            ids = [l["id"] for l in cur_lines]
            pos = ids.index(tile_id)
            if action == "left" and pos > 0:
                ids[pos - 1], ids[pos] = ids[pos], ids[pos - 1]
            elif action == "right" and pos < len(ids) - 1:
                ids[pos + 1], ids[pos] = ids[pos], ids[pos + 1]
            backend.update_tile_order(ids)
        draw_tiles()

    edit_state = {"on": False}

    def on_edit_mode(e):
        edit_state["on"] = bool(e.value)
        draw_tiles()

    def _sync_progress(bar, model, mode, offset, count, page_size):
        # runs in the worker thread : schedule the bar update on the UI loop
        kind = {"full": "initial extract", "delta": "update"}.get(mode, "update")
        bar.set_value(offset + count).set_text(f"{kind} : {model}")
        bar.set_visibility(True)

    sync_holder = {"bar": None}

    async def on_refresh_data():
        def _progress(model, mode, offset, count, page_size):
            if sync_holder["bar"] is not None:
                _sync_progress(
                    sync_holder["bar"], model, mode, offset, count, page_size
                )

        await run.io_bound(kpiten_service.request_refresh, backend.db, _progress)
        # the user's own view again (column ACL, record rules, lang) : never the
        # raw store, which holds every row of every user
        fresh = await run.io_bound(user_store, backend, user_id)
        store_cache.clear()
        store_cache.update(fresh)
        ui.notify("Data synced with Odoo")
        if sync_holder["bar"] is not None:
            sync_holder["bar"].set_visibility(False)
        draw_tiles()

    palette = THEMES[theme_key]
    light = palette["theme"] == "light"
    with (
        ui.column()
        .style(theme_style(palette))
        .classes("bb-ktd w-full p-6" + (" bb-ktd-light" if light else ""))
    ):
        with ui.row().classes("w-full items-center gap-4 flex-wrap mb-2"):
            # framework logo, linking to the app origin
            with ui.link(target="https://nicegui.io", new_tab=True):
                ui.image("/static/logo.png").classes("framework-logo").tooltip(
                    "Made with NiceGUI"
                )
            ui.select(
                options=panels_map,
                value=str(state_panel),
                on_change=on_panel_change,
                label="Panel",
            ).props("dark dense outlined").props(
                'popup-content-class="bb-menu-dark"'
            ).classes(
                "w-48"
            )
            ui.select(
                options=databases,
                value=backend.db,
                on_change=lambda e: ui.navigate.to(f"/?theme={theme_key}&db={e.value}"),
                label="Database",
            ).props("dark dense outlined").props(
                'popup-content-class="bb-menu-dark"'
            ).classes(
                "w-44"
            ).tooltip(
                "Odoo database (each db has its own parquet snapshot)"
            )
            ui.select(
                options={key: theme["name"] for key, theme in THEMES.items()},
                value=theme_key,
                on_change=lambda e: ui.navigate.to(f"/?theme={e.value}"),
                label="Theme",
            ).props("dark dense outlined").props(
                'popup-content-class="bb-menu-dark"'
            ).classes(
                "w-32"
            )
            sync_holder["bar"] = (
                ui.linear_progress(value=0, show_value=True)
                .props("striped")
                .classes("w-64")
                .set_visibility(False)
            )
            ui.button("Refresh data", on_click=on_refresh_data)
            ui.button("Refresh tiles", on_click=draw_tiles).props("flat")
            if can_edit:
                ui.switch("Edit mode", value=False, on_change=on_edit_mode).props(
                    "dark"
                )
            stamp = last_sync(backend, user_id)
            if stamp:
                ui.label("⏱ " + stamp).classes("text-xs opacity-55").tooltip(
                    "Data as of " + stamp + " — 'Refresh data' syncs with Odoo"
                )
        with ui.column().classes("w-full"):
            filters_row = ui.row().classes("w-full items-end gap-4")
            cards_grid = ui.element("div").classes("tile-grid card-grid w-full")
            tiles_grid = ui.element("div").classes("tile-grid w-full")
        draw_filters()

    draw_tiles()


def create_server():
    """FastAPI wrapper exposing the nicegui dashboard + SSO (shiny-like).

    - POST / : Odoo posts {"user_uuid": ...} ; we validate it against Odoo
      (kpiten-core Backend) and return a session token ; the dashboard
      syncs the data itself.
    - GET /dashboard/auth?session=... : validates the token, then
      redirects to the nicegui UI mounted at /dashboard.
    """
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    sso_app = FastAPI()

    @sso_app.post("/kpiten/tile-order")
    def tile_order(request: Request, payload: dict):
        """Save the dragged tile sequence (EDIT_JS fetch from the browser)."""
        from kpiten_core import env

        sso = SessionHandler.get(request.cookies.get(SESSION_COOKIE))
        if sso is None and not env.allow_rpc_user:
            return JSONResponse(status_code=403, content={"error": "Not connected"})
        try:
            backend = Backend.create(db=sso.db if sso else None)
            user_id = sso.user_id if sso else backend.env.user.id
            if not backend.can_edit_tiles(user_id):
                return JSONResponse(
                    status_code=403, content={"error": "Only a KpiTen manager can edit"}
                )
            backend.update_tile_order([int(i) for i in payload.get("ids", [])])
        except Exception:
            logger.exception("tile order save failed")
            return JSONResponse(
                status_code=500, content={"error": "Tile order save failed"}
            )
        return JSONResponse(content={"ok": True})

    @sso_app.post("/")
    def auth(payload: dict):
        if not payload or not payload.get("user_uuid"):
            return JSONResponse(
                status_code=403, content={"error": "No user_uuid provided"}
            )
        try:
            # db may be provided by the odoo side (action_redirect_to_kpiten)
            backend = Backend.create(db=payload.get("db"))
            user_id = backend.check_uuid(payload["user_uuid"])
            if user_id is None:
                return JSONResponse(
                    status_code=403,
                    content={"error": "No user matches this uuid"},
                )
            from kpiten_core import env

            # scope the parquet store to this db ; the dashboard triggers the
            # actual sync itself (empty store on first render, or the
            # "Refresh data" button).
            env.current_db = backend.db
        except Exception:
            logger.exception("sso auth failed")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "The server is unavailable. Please try again later !"
                },
            )
        token = SessionHandler.new_session(user_id, db=backend.db)
        return JSONResponse(content={"session": token})

    @sso_app.get("/dashboard/auth")
    def check_session(session: str):
        sso = SessionHandler.get(session)
        if sso is None:
            return JSONResponse(
                status_code=403,
                content={"error": "No session registered for this token"},
            )
        # the token goes in a cookie : the dashboard reads it to know who is
        # connected (one session per user, nothing shared between users)
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session,
            httponly=True,
            samesite="lax",
            path="/",  # the drag & drop also posts to /kpiten/tile-order
            max_age=int(sso.VALIDITY_TIME.total_seconds()),
        )
        return response

    ui.run_with(
        sso_app,
        title="KpiTen (nicegui)",
        mount_path="/dashboard",
        storage_secret="kpiten",
    )
    return sso_app


if __name__ in {"__main__", "__mp_main__"}:
    logging.basicConfig(level=logging.INFO)
    import uvicorn

    uvicorn.run(create_server(), host="0.0.0.0", port=5001)
