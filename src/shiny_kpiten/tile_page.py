"""One tile alone, as the dashboard draws it : the page of the iframe that shows a KPI in
its form in Odoo (`GET /dashboard/tile/<id>?session=...`).

The session is the one of the user in Odoo (its SSO, a token in the url : no cookie in
the iframe) : the tile is computed with their rights, on the synced data, over the
default period of `kt.config`, in their theme and their language.
"""

import html
import logging

from kpiten_core import config as core_config
from kpiten_core import filters, i18n
from kpiten_core import labels as core_labels
from kpiten_core import links
from kpiten_core import tiles as core_tiles
from kpiten_core.backend import Backend
from kpiten_core.render.gtable import DRILL_CSS

from . import data as data_layer
from . import themes
from .app import PLOTLY_JS, tile_error_html, tile_html

logger = logging.getLogger(__name__)


def _page(body: str, css: str = "") -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<script src="{PLOTLY_JS}"></script>'
        f"<style>{css}{links.LINK_CSS}{DRILL_CSS}"
        # the font of the dashboard (bootstrap's : the one of the system)
        "body { margin: 0; padding: 8px; font-family: system-ui, -apple-system,"
        ' "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif }'
        " .tile { margin: 0 }</style>"
        f'</head><body class="kpiten-dashboard">{body}</body></html>'
    )


def _message(text: str) -> str:
    return _page(
        f'<p style="font-family: sans-serif; opacity: .7">{html.escape(text)}</p>'
    )


def tile_page(tile_id: int, sso) -> str:
    """The html of the tile `tile_id` for the user of the session `sso`."""
    tr = i18n.translator(sso.lang)
    backend = Backend.create(db=sso.db)
    core_tiles.set_chart_config(backend.get_chart_config())
    kpi = backend.call(backend.kpi_model, "read", ids=[tile_id], fields=["panel_id"])
    if not kpi or not kpi[0]["panel_id"]:
        return _message(tr("Put the KPI on a panel to see it."))
    panel_id = kpi[0]["panel_id"][0]
    line = next(
        (
            t
            for t in backend.get_panel_tiles(panel_id, sso.user_id)
            if t["id"] == tile_id
        ),
        None,
    )
    if line is None:
        return _message(tr("This KPI is not visible to you."))
    theme = themes.get_theme(
        backend.get_user_theme(sso.user_id) or core_config.default_theme()
    )
    store = data_layer.user_store(backend, sso.user_id)
    if not store:
        return _message(tr("No data yet : open the dashboard once to sync it."))
    config = backend.get_panel_settings(panel_id).get("filter_config") or {}
    date_value = filters.bounds_of_option(core_config.default_period())
    try:
        result = core_tiles.exec_tile(
            line,
            line["model"],
            store,
            filters.make_predicates(config, date_value, {}),
            filters.make_previous_predicates(config, date_value, {}),
            filters.describe_previous(date_value),
            core_labels.field_labels_of(backend, sso.lang),
        )
        body = tile_html(line, theme, result, tr=tr)
    except Exception as err:
        logger.exception("the preview of tile %s failed", tile_id)
        body = tile_error_html(line, str(err))
    return _page(body, theme.css())
