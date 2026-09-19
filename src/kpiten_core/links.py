"""Links from a tile to the Odoo record it shows.

A table cell holding `[label](url)` is rendered as a link (see `gtable`). A
`data` snippet builds it from the `odoo_url` variable the sandbox gives it :

    pl.concat_str([pl.lit("["), pl.col("partner_id"), pl.lit("]("),
                   pl.lit(odoo_url), pl.lit("/odoo/sale.order/"),
                   pl.col("id").cast(pl.String), pl.lit(")")])

The label is data (a customer name typed by any Odoo user) : it is escaped, and
only links to Odoo itself are followed, whatever a snippet builds.
"""

import html
import re

import polars as pl

# the label may hold brackets and parentheses : it is what is left between the
# first "[" and the last "](" ; the url has no space and no ")"
LINK_PATTERN = r"(?s)^\[.*\]\(https?://[^\s)]+\)$"
LINK_RE = re.compile(LINK_PATTERN)
_PARTS_RE = re.compile(r"(?s)^\[(?P<label>.*)\]\((?P<url>https?://[^\s)]+)\)$")

# Every link inside a tile opens in a new tab. The browser does it at click time
# because a front that sanitizes its html drops the attributes : NiceGUI's
# `setHTML` removes `target`, `rel` and `style` from an <a>, so `target="_blank"`
# in `link_html` alone is not enough there. Run once per page.
NEW_TAB_JS = """
(function () {
  if (window.__kpitenNewTab) { return; }
  window.__kpitenNewTab = true;
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest ? ev.target.closest(".tile a[href]") : null;
    if (link) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
  }, true);
})();
"""

# The links of a table are not underlined : an arrow after the label says the
# record opens in another tab (the same css for both fronts).
LINK_CSS = """
.tile .gt_table a[href], .modal .gt_table a[href], .q-dialog .gt_table a[href] { text-decoration: none; }
.tile .gt_table a[href]::after, .modal .gt_table a[href]::after, .q-dialog .gt_table a[href]::after {
  content: "\\2197";
  font-size: .8em;
  margin-left: .2em;
  opacity: .7;
}
"""

_odoo_url = ""


def set_odoo_url(url: str | None) -> None:
    """The base url of Odoo the links point to (see `Backend.get_base_url`)."""
    global _odoo_url
    _odoo_url = (url or "").rstrip("/")


def get_odoo_url() -> str:
    return _odoo_url


def is_odoo_url(url: str) -> bool:
    base = _odoo_url
    return bool(base) and (url == base or url.startswith(base + "/"))


def link_columns(df: pl.DataFrame) -> list[str]:
    """The text columns whose every value is a `[label](url)` link (nulls
    apart) : those are drawn as links."""
    columns = []
    for name, dtype in df.schema.items():
        if dtype != pl.String:
            continue
        values = df[name].drop_nulls()
        if values.len() and values.str.contains(LINK_PATTERN).all():
            columns.append(name)
    return columns


def link_html(value: str | None, color: str | None = None) -> str:
    """The html of a cell : an `<a>` for a link to Odoo, else the escaped text."""
    if value is None:
        return ""
    match = _PARTS_RE.match(value)
    if not match or not is_odoo_url(match["url"]):
        return html.escape(value)
    style = f' style="color: {html.escape(color, quote=True)}"' if color else ""
    return (
        f'<a href="{html.escape(match["url"], quote=True)}" target="_blank" '
        f'rel="noopener noreferrer"{style}>{html.escape(match["label"])}</a>'
    )
