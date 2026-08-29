import marimo as mo
from pathlib import Path

_STYLE_FILE = Path(__file__).resolve().parents[2] / "styles" / "first.css"


def load_style() -> str:
    """Read the shared stylesheet."""
    return _STYLE_FILE.read_text()


def style_html():
    return mo.Html(f"<style>{load_style()}</style>")


def nav_menu(target: str, label: str):
    return mo.nav_menu({target: label})


def no_data(mo, callout):
    mo.stop(not callout)
    return callout


def select(options: list, value=None, max_selections: int = 1):
    kwargs = {"options": options, "max_selections": max_selections}
    if value is not None:
        kwargs["value"] = value
    return mo.ui.multiselect(**kwargs)
