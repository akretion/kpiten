"""A tile result as html for an Odoo form (kpiten-core computes, this only draws)."""

import html

from odoo import models

# the light palette of a table in the Odoo backend (gtable takes a theme palette)
PALETTE = {
    "surface_hex": "#ffffff",
    "text": "#212529",
    "thead": "#f1f3f5",
    "border_hex": "#dee2e6",
    "row_line": "#e9ecef",
    "accent": "#714b67",
}


class KtPreviewRender(models.AbstractModel):
    _name = "kt.preview.render"
    _description = "Html of a KpiTen tile result"

    def error_html(self, message):
        return f'<div class="alert alert-danger">{html.escape(message)}</div>'

    def result_html(self, line, result):
        """The tile result of kpiten-core as html."""
        title = f"<h5>{html.escape(line.name or result.kind)}</h5>"
        if result.kind == "card":
            body = f'<div class="display-6">{html.escape(result.text)}</div>'
            if result.subtitle:
                body += f'<div class="text-muted">{html.escape(result.subtitle)}</div>'
        elif result.kind == "graph":
            # plotly needs its script : it runs in an iframe of its own
            page = result.figure.to_html(include_plotlyjs="cdn", full_html=True)
            body = (
                f'<iframe srcdoc="{html.escape(page, quote=True)}" '
                'style="width: 100%; height: 420px; border: 0"></iframe>'
            )
        else:
            from kpiten_core.render.gtable import gt_table

            body = gt_table(result.df, PALETTE).as_raw_html()
        if result.note:
            body += f'<div class="text-muted small">{html.escape(result.note)}</div>'
        return title + body
