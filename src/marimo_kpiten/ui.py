"""Small pieces the notebooks share."""

import html

import marimo as mo
import polars as pl

from kpiten_core import brand, config, links, numfmt
from kpiten_core.gtable import number_columns

from .analyses import ANALYSES

ARROW = '<span style="opacity:.7;margin-left:.2em;font-size:.8em">↗</span>'


def odoo_link(label, url: str) -> mo.Html:
    """A link to a record in Odoo. It opens in another tab : the arrow says so."""
    return mo.Html(
        f'<a href="{html.escape(url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer" style="text-decoration:none">'
        f"{html.escape(str(label))}{ARROW}</a>"
    )


def brand_mark(height: int = 30) -> mo.Html:
    """The logo of KpiTen, with its slogan on hover."""
    tip = html.escape(brand.tooltip(), quote=True).replace("\n", "&#10;")
    return mo.Html(
        f'<img src="/dashboard/kpiten.png" alt="{brand.NAME}" title="{tip}" '
        f'height="{height}" style="height:{height}px;width:{height}px">'
    )


def footer() -> mo.Html:
    """The logo of KpiTen with its name, at the end of a page, on the right."""
    tip = html.escape(brand.tooltip(), quote=True)
    return mo.Html(
        f'<div style="display:flex;justify-content:flex-end;margin-top:32px" title="{tip}">'
        f"{brand.lockup_svg(64)}</div>"
    )


def framework_mark(height: int = 28) -> mo.Html:
    """The logo of marimo (the framework), which marimo serves itself."""
    return mo.Html(
        f'<img src="/dashboard/logo.png" alt="marimo" title="Made with marimo" '
        f'style="height:{height}px;width:auto">'
    )


def header(key: str, user_id, db) -> mo.Html:
    """Title of an analysis, with the way back to the list and who is connected."""
    analysis = ANALYSES[key]
    return mo.vstack(
        [
            mo.hstack(
                [
                    # the logo of KpiTen on the left, the one of the framework on the right
                    mo.hstack(
                        [
                            brand_mark(56),
                            mo.md("<small>[← Marimo notebook](/dashboard/)</small>"),
                        ],
                        justify="start",
                        align="center",
                        gap=0.8,
                    ),
                    framework_mark(),
                ],
                justify="space-between",
                align="center",
            ),
            mo.md(f"""
                # {analysis["icon"]} {analysis["title"]}
                <small>user `{user_id}` on `{db}` : only the rows and columns you may read in Odoo</small>
                """),
        ]
    )


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
        table = plain(answer.table)
        # numbers as the dashboards write them (`kt.config` : format, rounding)
        integers, decimals = number_columns(table)
        shown = {c: numfmt.format_number for c in integers}
        shown.update({c: numfmt.format_quantity for c in decimals})
        parts.append(
            mo.ui.table(table, selection=None, page_size=10, format_mapping=shown)
        )
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
