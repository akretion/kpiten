"""The hooks a plugin of kpiten may implement (pluggy).

A plugin is a module registered in the `kpiten_core` entry points group (see
`plugins.py`) ; its functions marked `@hookimpl` answer the hooks below :

    from kpiten_core.hookspecs import hookimpl

    @hookimpl
    def kpiten_render_tile(line, result, palette):
        if "my marker" in (line.get("content") or ""):
            return "<div>...</div>"

The fronts ask the plugins through `plugins.head_html()` and `plugins.render_tile()`.
"""

import pluggy

PROJECT = "kpiten"
hookspec = pluggy.HookspecMarker(PROJECT)
hookimpl = pluggy.HookimplMarker(PROJECT)


@hookspec
def kpiten_head_html() -> str:
    """Html for the <head> of a dashboard page : the scripts and styles the tiles of
    the plugin need (loaded once per page)."""


@hookspec(firstresult=True)
def kpiten_render_tile(line: dict, result, palette: dict) -> str | None:
    """The html of the body of a tile, in place of the front's own drawing ; None to
    leave the tile to the front (or to another plugin).

    `line` is the tile (`kt.dataset.line` : its `content`, `name`, `kind`...),
    `result` its `tiles.TileResult` (the rows the user may read, already computed),
    `palette` the colors of the theme (`themes.PALETTES`)."""


@hookspec
def kpiten_panel_exports() -> list[dict]:
    """The exports of a whole panel the plugin offers, one dict each :
    `{"key": "pdf", "label": "PDF report", "icon": "<svg...>", "tooltip": "...",
    "extension": "pdf", "media_type": "application/pdf"}` ; the front shows a button
    per export."""


@hookspec(firstresult=True)
def kpiten_export_panel(
    key: str, panel: dict, tiles: list, context: dict
) -> bytes | None:
    """The file of the export `key` of the panel, None when it is not the plugin's.

    `panel` : `{"id", "name"}` ; `tiles` : one `(line, result, error)` per tile of the
    panel, in its order (`result` a `tiles.TileResult` computed with the period, the
    filters and the rights of the user, or None and the `error` text) ; `context` :
    `{"filters": text, "user": name, "db": name, "palette": theme colors, "date": date}`.
    """


@hookspec
def kpiten_panel_sites() -> list[dict]:
    """The sites of a panel the plugin builds, one dict each :
    `{"key": "evidence", "label": "Evidence", "icon": "<svg...>", "tooltip": "..."}` ;
    the front shows a button per site, and serves the site it built."""


@hookspec(firstresult=True)
def kpiten_build_panel_site(
    key: str, panel: dict, tiles: list, context: dict, folder, base_path: str
) -> bool | None:
    """Build the static site `key` of the panel in `folder` (a `pathlib.Path`), to be
    served at `base_path` (`/dashboard/sites/<token>`) ; None when it is not the
    plugin's. `panel`, `tiles`, `context` : as for `kpiten_export_panel`."""
