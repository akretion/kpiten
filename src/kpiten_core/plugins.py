"""Plugin/addon mechanism for kpiten-core.

A plugin is a python package (or module) that extends kpiten-core
behavior. Plugins can either:

- register dataframe-prep hooks (per table) through
  `kpiten_core.hooks.register_df` (i.e. custom transformations applied
  right after extraction), or
- implement any function of the `Backend` API and monkeypatch /
  subclass in place.

- implement the hooks of `hookspecs.py` (pluggy) : draw a tile, add scripts to the
  page (`plugin_manager`, `head_html`, `render_tile`).

Discovery is based on the `kpiten_core` entry points group:

```toml
[project.entry-points."kpiten_core"]
my_plugin = "my_plugin_package"
```

or explicitly, from the app:

```python
from kpiten_core.plugins import load_plugins
load_plugins(["my_project.plugins_ext"])  # module path is python import name
"""

import functools
import importlib
import logging
from importlib.metadata import entry_points

import pluggy

from kpiten_core import hookspecs

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "kpiten_core"


def load_plugins(module_names: list[str] | None = None) -> list[str]:
    """Load plugins from entry points and explicit module names."""
    register = {ep.name: ep.load() for ep in entry_points(group=ENTRY_POINT_GROUP)}
    mods = []
    for name in [*(module_names or []), *register.values()]:
        try:
            mod = importlib.import_module(name)
        except Exception:
            logger.exception("failed to load plugin module '%s'", name)
            continue
        init = getattr(mod, "init_plugin", None)
        if callable(init):
            init()
        mods.append(name)
    logger.info("loaded plugins : %s", mods)
    return mods


# ---- pluggy : the hooks of `hookspecs.py`, answered by the plugins of the same entry
# points group
@functools.cache
def plugin_manager() -> pluggy.PluginManager:
    """The plugin manager, with the plugins of the `kpiten_core` entry points."""
    manager = pluggy.PluginManager(hookspecs.PROJECT)
    manager.add_hookspecs(hookspecs)
    try:
        manager.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
    except Exception:
        logger.exception("failed to load the kpiten plugins")
    logger.info("kpiten plugins : %s", [n for n, _ in manager.list_name_plugin()])
    return manager


def head_html() -> str:
    """What the plugins put in the <head> of a dashboard page."""
    return "\n".join(filter(None, plugin_manager().hook.kpiten_head_html()))


def render_tile(line: dict, result, palette: dict) -> str | None:
    """The html of a tile drawn by a plugin, None when no plugin draws it."""
    try:
        return plugin_manager().hook.kpiten_render_tile(
            line=line, result=result, palette=palette
        )
    except Exception:
        logger.exception("a plugin failed to draw the tile %s", line.get("name"))
        return None


def panel_exports() -> list[dict]:
    """The exports of a panel the plugins offer (a button each in the front)."""
    return [
        export
        for exports in plugin_manager().hook.kpiten_panel_exports()
        for export in exports or ()
    ]


def export_panel(key: str, panel: dict, tiles: list, context: dict) -> bytes | None:
    """The file of an export of the panel (see `hookspecs.kpiten_export_panel`)."""
    return plugin_manager().hook.kpiten_export_panel(
        key=key, panel=panel, tiles=tiles, context=context
    )
