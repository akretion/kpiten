"""The panel on screen as a PDF report : Markdown rendered by Quarto through Typst.

The tiles come computed by the front (period, filters and rights of the user) :
- the cards are a table (value, change against the previous period) ;
- a graph is a PNG (kaleido, which drives a Chrome) ;
- a table keeps its first rows and its `[label](url)` links to Odoo.
"""

import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import plotly.io as pio
import polars as pl

from kpiten_core import comparison, config, numfmt, themes
from kpiten_core import tiles as core_tiles
from kpiten_core.hookspecs import hookimpl

logger = logging.getLogger(__name__)

KEY = "pdf"
ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
    '<path d="M14 3v5h5M9 13h6M9 17h4"/></svg>'
)
EXPORT = {
    "key": KEY,
    "label": "PDF",
    "icon": ICON,
    "tooltip": "Download the panel as a PDF report : its period, its filters, your rows",
    "extension": "pdf",
    "media_type": "application/pdf",
}
GRAPH_SIZE = {"width": 1000, "height": 450, "scale": 2}


# ---- the tools : Quarto (quarto-cli, in the venv) and a Chrome for kaleido
def quarto_bin() -> str:
    found = shutil.which("quarto", path=str(Path(sys.executable).parent))
    found = found or shutil.which("quarto")
    if not found:
        raise RuntimeError("Quarto is not installed (pip install quarto-cli)")
    return found


def use_chrome() -> None:
    """kaleido needs a Chrome : `KPITEN_CHROME`, else the one of playwright."""
    if os.environ.get("BROWSER_PATH"):
        return
    chrome = os.environ.get("KPITEN_CHROME") or next(
        iter(
            sorted(
                glob.glob(
                    os.path.expanduser(
                        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"
                    )
                ),
                reverse=True,
            )
        ),
        None,
    )
    if chrome:
        os.environ["BROWSER_PATH"] = chrome


# ---- markdown
def _cell(value) -> str:
    """A value as a cell of a pipe table (a `[label](url)` stays a link)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "✓" if value else ""
    if isinstance(value, int):
        return numfmt.format_number(value)
    if isinstance(value, float) or type(value).__name__ == "Decimal":
        return numfmt.format_quantity(float(value))
    return str(value).replace("|", "\\|").replace("\n", " ")


def table_md(df: pl.DataFrame) -> str:
    numeric = [dtype.is_numeric() for dtype in df.dtypes]
    head = "| " + " | ".join(_cell(c) for c in df.columns) + " |"
    rule = "|" + "|".join("--:" if n else "---" for n in numeric) + "|"
    rows = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in df.iter_rows()]
    return "\n".join([head, rule, *rows])


def cards_md(cards: list) -> str:
    lines = ["| Indicator | Value | Change |", "|---|--:|---|"]
    for line, result, error in cards:
        name = _cell(line.get("name") or "")
        if result is None:
            lines.append(f"| {name} | | _{_cell(error)}_ |")
            continue
        change = ""
        if result.comparison:
            change = (
                f"{comparison.label(result.comparison)} "
                f"{result.comparison.get('description', '')}"
            )
        value = result.text + (f" ({result.subtitle})" if result.subtitle else "")
        lines.append(f"| {name} | **{_cell(value)}** | {_cell(change)} |")
    return "\n".join(lines)


def print_palette(palette: dict) -> dict:
    """The colors of the graphs on paper : the theme's when its tiles are light."""
    surface = palette.get("surface_hex", "#ffffff")
    dark = int(surface[1:3], 16) + int(surface[3:5], 16) + int(surface[5:7], 16) < 384
    return themes.PALETTES["light"] if dark else palette


def document(panel: dict, tiles: list, context: dict, folder: Path) -> str:
    """The .qmd of the report ; the graphs are written in `folder`."""
    palette = print_palette(context.get("palette") or {})
    front = {
        "title": panel.get("name") or "KpiTen",
        "subtitle": context.get("filters") or "",
        "author": context.get("user") or "",
        "date": str(context.get("date") or ""),
        "format": {"typst": {"papersize": "a4", "margin": {"x": "1.6cm", "y": "1.8cm"}}},
    }
    # json is yaml : the strings are quoted and escaped
    parts = ["---", *(f"{k}: {json.dumps(v)}" for k, v in front.items()), "---", ""]
    cards = [t for t in tiles if t[0].get("kind") == "card"]
    if cards:
        parts += ["## Key figures", "", cards_md(cards), ""]
    figures, paths = [], []
    rows = config.table_rows()
    for line, result, error in tiles:
        if line.get("kind") == "card":
            continue
        parts += [f"## {line.get('name') or line.get('kind')}", ""]
        if result is None:
            parts += [f"_{_cell(error)}_", ""]
        elif result.figure is not None:
            fig = result.figure
            core_tiles.apply_theme_colors(fig, palette)
            fig.update_layout(
                template="plotly_white",
                paper_bgcolor="white",
                plot_bgcolor="white",
                font={"size": 12},
                margin={"l": 40, "r": 20, "t": 20, "b": 40},
            )
            path = folder / f"graph-{line.get('id')}.png"
            figures.append(fig)
            paths.append(path)
            parts += [f"![]({path.name}){{width=100%}}", ""]
        elif result.df is not None:
            total = result.meta.get("total_rows", result.df.height)
            parts += [table_md(result.df.head(rows)), ""]
            if total > rows:
                parts += [f"_First {rows} of {numfmt.format_number(total)} rows_", ""]
        if result is not None and result.note:
            parts += [f"_{_cell(result.note)}_", ""]
    if figures:
        use_chrome()
        pio.write_images(figures, paths, **GRAPH_SIZE)  # one Chrome for all
    return "\n".join(parts)


def render_pdf(panel: dict, tiles: list, context: dict) -> bytes:
    folder = Path(tempfile.mkdtemp(prefix="kpiten-quarto-"))
    try:
        (folder / "report.qmd").write_text(document(panel, tiles, context, folder))
        done = subprocess.run(
            [quarto_bin(), "render", "report.qmd", "--to", "typst"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if done.returncode:
            logger.error("quarto : %s", done.stderr[-3000:])
            raise RuntimeError(f"Quarto failed : {done.stderr.strip()[-300:]}")
        return (folder / "report.pdf").read_bytes()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@hookimpl
def kpiten_panel_exports() -> list[dict]:
    return [EXPORT]


@hookimpl
def kpiten_export_panel(key, panel, tiles, context) -> bytes | None:
    if key != KEY:
        return None
    return render_pdf(panel, tiles, context)
