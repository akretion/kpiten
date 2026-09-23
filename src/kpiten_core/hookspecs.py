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
