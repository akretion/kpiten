"""Small pieces the notebooks share."""

import html

import marimo as mo
import polars as pl

from kpiten_core import config, links

from .analyses import ANALYSES

ARROW = '<span style="opacity:.7;margin-left:.2em;font-size:.8em">↗</span>'


def odoo_link(label, url: str) -> mo.Html:
    """A link to a record in Odoo. It opens in another tab : the arrow says so."""
    return mo.Html(
        f'<a href="{html.escape(url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer" style="text-decoration:none">'
        f"{html.escape(str(label))}{ARROW}</a>"
    )


def header(key: str, user_id, db) -> mo.Html:
    """Title of an analysis, with the way back to the list and who is connected."""
    analysis = ANALYSES[key]
    return mo.md(f"""
        <small>[← Marimo notebook](/dashboard/)</small>

        # {analysis["icon"]} {analysis["title"]}
        <small>user `{user_id}` on `{db}` : only the rows and columns you may read in Odoo</small>
        """)


def plain(frame: pl.DataFrame) -> pl.DataFrame:
    """The frame with its decimals as floats (what a marimo table draws well)."""
    decimals = [c for c, t in frame.schema.items() if t.is_decimal()]
    return frame.with_columns(pl.col(decimals).cast(pl.Float64)) if decimals else frame


def ai_answer(answer) -> mo.Html:
    """An answer of the AI : its words, the code it ran, the table it computed."""
    parts = [mo.md(answer.text)] if answer.text else []
    if answer.code:
        parts.append(mo.accordion({"Code": mo.md(f"```python\n{answer.code}\n```")}))
    if answer.table is not None:
        parts.append(mo.md(f"**{answer.table.height}** rows"))
        parts.append(mo.ui.table(plain(answer.table), selection=None, page_size=10))
    if answer.error and answer.table is None and answer.code:
        parts.append(
            mo.callout(
                mo.md(f"The code does not run : `{answer.error}`"), kind="danger"
            )
        )
    return mo.vstack(parts)


def load_settings(backend) -> None:
    """The settings of `kt.config` (Odoo) for this notebook : number format, the switches
    of the AI... A notebook calls it once, with the backend of its session."""
    config.set_config(backend.get_chart_config())


def records_link(backend, odoo_url: str, model: str, ids: list[int]):
    """A link that opens, in Odoo, the records a table lists : the same list, with the
    rights of the user there. None unless the feature is on in `kt.config`, or when Odoo
    has no list action for the model."""
    if not config.feature("open_in_odoo") or not ids:
        return None
    try:
        action = backend.get_records_action_id(model)
    except Exception:
        return None
    url, count = links.records_url(odoo_url, action, ids)
    label = (
        f"Open these {count} records in Odoo"
        if count == len(ids)
        else f"Open the first {count} of {len(ids)} records in Odoo"
    )
    return odoo_link(label, url)
