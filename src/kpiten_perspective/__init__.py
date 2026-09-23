"""A `data` tile drawn by Perspective (FINOS) : a pivot the user moves in the browser.

The tile is chosen by a line of its definition, the config of the viewer as json :

    -- perspective: {"group_by": ["Salesperson"], "split_by": ["Year"], "columns": ["Revenue"]}

The rows of the tile (the ones the user may read, filtered by the panel) go to the
page as Arrow ; the `<kpiten-perspective>` element (`HEAD`) loads Perspective from the
CDN once per page and hands them to a `<perspective-viewer>`.
"""

import base64
import html
import io
import json
import re

import polars as pl

from kpiten_core.hookspecs import hookimpl

VERSION = "3.8.0"
CDN = "https://cdn.jsdelivr.net/npm/@finos"
MARKER = re.compile(r"^\s*(?:--|#)\s*perspective\s*:\s*(\{.*\})\s*$", re.MULTILINE)

HEAD = f"""
<link rel="stylesheet" crossorigin="anonymous"
      href="{CDN}/perspective-viewer@{VERSION}/dist/css/themes.css">
<style>
kpiten-perspective {{ display: block; height: 360px; min-width: 0 }}
kpiten-perspective perspective-viewer {{ height: 100%; border-radius: 8px }}
kpiten-perspective .kpiten-perspective-error {{ font-size: 12px; opacity: .8 }}
</style>
<script>
(function () {{
  if (customElements.get("kpiten-perspective")) {{ return; }}
  const CDN = "{CDN}", V = "{VERSION}";
  let worker = null;
  // Perspective is loaded once per page, on the first tile that needs it
  function load() {{
    worker = worker || (async function () {{
      await Promise.all([
        import(`${{CDN}}/perspective-viewer@${{V}}/dist/cdn/perspective-viewer.js`),
        import(`${{CDN}}/perspective-viewer-datagrid@${{V}}/dist/cdn/perspective-viewer-datagrid.js`),
        import(`${{CDN}}/perspective-viewer-d3fc@${{V}}/dist/cdn/perspective-viewer-d3fc.js`),
      ]);
      const perspective = (await import(`${{CDN}}/perspective@${{V}}/dist/cdn/perspective.js`)).default;
      return perspective.worker();
    }})();
    return worker;
  }}
  class KpitenPerspective extends HTMLElement {{
    async connectedCallback() {{
      if (this.viewer) {{ return; }}
      this.viewer = document.createElement("perspective-viewer");
      this.appendChild(this.viewer);
      try {{
        const bytes = Uint8Array.from(atob(this.dataset.arrow), c => c.charCodeAt(0));
        this.table = await (await load()).table(bytes.buffer);
        await this.viewer.load(this.table);
        const config = JSON.parse(this.dataset.config || "{{}}");
        await this.viewer.restore({{theme: this.dataset.theme, ...config}});
      }} catch (err) {{
        const note = document.createElement("div");
        note.className = "kpiten-perspective-error";
        note.textContent = "Perspective : " + err;
        this.replaceChildren(note);
      }}
    }}
    // a tile drawn again (a filter changed) : free the table of the old one
    disconnectedCallback() {{
      const viewer = this.viewer, table = this.table;
      this.viewer = this.table = null;
      Promise.resolve(viewer && viewer.delete && viewer.delete())
        .then(() => table && table.delete())
        .catch(() => null);
    }}
  }}
  customElements.define("kpiten-perspective", KpitenPerspective);
}})();
</script>
"""


def config_of(content: str | None) -> dict | None:
    """The config of the viewer the definition asks for, None when it asks for none."""
    match = MARKER.search(content or "")
    return json.loads(match[1]) if match else None


def arrow_base64(df: pl.DataFrame) -> str:
    """The rows as an Arrow stream, in base64 : the decimals as floats, the oldest
    Arrow types (Perspective reads no decimal, no string view)."""
    df = df.with_columns(pl.col(pl.Decimal).cast(pl.Float64))
    buffer = io.BytesIO()
    df.write_ipc_stream(buffer, compat_level=pl.CompatLevel.oldest())
    return base64.b64encode(buffer.getvalue()).decode()


def _is_dark(color: str) -> bool:
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 128


@hookimpl
def kpiten_head_html() -> str:
    return HEAD


@hookimpl
def kpiten_render_tile(line: dict, result, palette: dict) -> str | None:
    if result is None or result.kind != "data" or result.df is None:
        return None
    config = config_of(line.get("content"))
    if config is None:
        return None
    # the viewer follows the tile (light tiles on a dark page for Mixed)
    theme = "Pro Dark" if _is_dark(palette.get("surface_hex", "#ffffff")) else "Pro Light"
    attr = lambda value: html.escape(value, quote=True)  # noqa: E731
    return (
        f'<kpiten-perspective data-theme="{theme}" '
        f'data-config="{attr(json.dumps(config))}" '
        f'data-arrow="{arrow_base64(result.df)}"></kpiten-perspective>'
    )
