"""The sites the plugins build for a user (`kpiten_core.hookspecs.kpiten_build_panel_site`,
kpiten-evidence...), served by `main.py` at `/dashboard/sites/<token>/` to that user only.

A site is built from the rows of its user : its token is never a way in for another
user (the route checks the SSO session). A site is reused for 15 minutes when the same
user asks for the same panel with the same filters ; an older one is removed.
"""

import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("KPITEN_SITES_DIR", "~/.cache/kpiten-sites")).expanduser()
PREFIX = "/dashboard/sites"
REUSE_SECONDS = 15 * 60


@dataclass
class Site:
    token: str
    user_id: int
    db: str
    key: tuple  # (plugin site, db, user, panel, filters) : what the site shows
    folder: Path
    created: float = field(default_factory=time.time)

    @property
    def base_path(self) -> str:
        return f"{PREFIX}/{self.token}"

    @property
    def root(self) -> Path:
        """The static files : the plugin builds them in `folder / "site"`."""
        return self.folder / "site"


_sites: dict[str, Site] = {}
_lock = threading.Lock()


def new(user_id: int, db: str, key: tuple) -> Site:
    """A site to build : its token and its (empty) folder, not served yet."""
    token = secrets.token_urlsafe(16)
    folder = ROOT / token
    folder.mkdir(parents=True)
    return Site(token, user_id, db, key, folder)


def recent(key: tuple) -> Site | None:
    """The site built for the same key less than 15 minutes ago, if any."""
    with _lock:
        found = [
            s
            for s in _sites.values()
            if s.key == key and time.time() - s.created < REUSE_SECONDS
        ]
    return max(found, key=lambda s: s.created) if found else None


def register(site: Site) -> None:
    """Serve the built site ; the older ones of the same key are removed."""
    with _lock:
        old = [s for s in _sites.values() if s.key == site.key]
        for s in old:
            del _sites[s.token]
        _sites[site.token] = site
    for s in old:
        discard(s)


def discard(site: Site) -> None:
    shutil.rmtree(site.folder, ignore_errors=True)


def get(token: str) -> Site | None:
    with _lock:
        return _sites.get(token)


def clean() -> None:
    """At the start of the app : the sites of before are no longer served (the list is
    in memory), their folders go (about 90 MB each)."""
    if ROOT.is_dir():
        for folder in ROOT.iterdir():
            shutil.rmtree(folder, ignore_errors=True)
