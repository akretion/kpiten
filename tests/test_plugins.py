"""The contract of the pluggy hooks (`hookspecs.py`), with a plugin registered by hand."""

import pytest

from kpiten_core import plugins
from kpiten_core.hookspecs import hookimpl


class Plugin:
    @hookimpl
    def kpiten_head_html(self):
        return "<script>/* the plugin */</script>"

    @hookimpl
    def kpiten_render_tile(self, line, result, palette):
        if "mine" in (line.get("content") or ""):
            return f"<div style='color:{palette['accent']}'>drawn</div>"
        return None  # the other tiles stay the front's

    @hookimpl
    def kpiten_panel_exports(self):
        return [{"key": "txt", "label": "Text", "extension": "txt"}]

    @hookimpl
    def kpiten_export_panel(self, key, panel, tiles, context):
        if key != "txt":
            return None
        return f"{panel['name']} : {len(tiles)} tiles for {context['user']}".encode()


@pytest.fixture
def plugin():
    manager = plugins.plugin_manager()
    registered = Plugin()
    manager.register(registered, name="test-plugin")
    yield registered
    manager.unregister(registered)


def test_a_plugin_adds_to_the_head_of_the_page(plugin):
    assert "/* the plugin */" in plugins.head_html()


def test_a_plugin_draws_only_its_tiles(plugin):
    palette = {"accent": "#123456"}
    drawn = plugins.render_tile({"content": "-- mine"}, None, palette)
    assert drawn == "<div style='color:#123456'>drawn</div>"
    assert plugins.render_tile({"content": "SELECT 1"}, None, palette) is None


def test_the_exports_of_the_plugins_and_the_file_of_one(plugin):
    assert {
        "key": "txt",
        "label": "Text",
        "extension": "txt",
    } in plugins.panel_exports()
    data = plugins.export_panel(
        "txt", {"id": 1, "name": "Sales"}, [("line", "result", None)], {"user": "Marie"}
    )
    assert data == b"Sales : 1 tiles for Marie"
    assert plugins.export_panel("pdf-of-nobody", {"name": "x"}, [], {}) is None


def test_a_plugin_that_fails_does_not_break_the_tile():
    class Broken:
        @hookimpl
        def kpiten_render_tile(self, line, result, palette):
            raise RuntimeError("boom")

    manager = plugins.plugin_manager()
    broken = Broken()
    manager.register(broken, name="broken-plugin")
    try:  # the front draws the tile itself
        assert plugins.render_tile({"name": "t"}, None, {}) is None
    finally:
        manager.unregister(broken)
