"""Plugin/addon mechanism for kpiten-core.

A plugin is a python package (or module) that extends kpiten-core
behavior. Plugins can either:

- register dataframe-prep hooks (per table) through
  `kpiten_core.hooks.register_df` (i.e. custom transformations applied
  right after extraction), or
- implement any function of the `Backend` API and monkeypatch /
  subclass in place.

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

import importlib
import logging
from importlib.metadata import entry_points
from typing import Callable

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
