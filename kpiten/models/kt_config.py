from odoo import _, api, fields, models

NUM_COLORS = 4


class KtConfig(models.Model):
    """
    One record only : the form view configuration page in old way
    Easy to maintain
    """

    _name = "kt.config"
    _description = "KpiTen configuration"
    _rec_name = "title"

    title = fields.Char(default="Configuration")
    graph_title_font_color = fields.Char(
        string="Graph title font color",
        help="Color of the chart title font (hex, e.g. #dbe4ef).",
    )
    graph_color_1 = fields.Char(
        string="Color 1",
        help="First color of the chart palette. Used for the first bar / "
        "series of each graph.",
    )
    graph_color_2 = fields.Char(
        string="Color 2",
        help="Second color of the chart palette. Used for the second bar / "
        "series of each graph.",
    )
    graph_color_3 = fields.Char(
        string="Color 3",
        help="Third color of the chart palette. Used for the third bar / "
        "series of each graph.",
    )
    graph_color_4 = fields.Char(
        string="Color 4",
        help="Fourth color of the chart palette. Used for the fourth bar / "
        "series of each graph.",
    )
    graph_color_preview = fields.Html(
        compute="_compute_graph_color_preview",
        sanitize=False,
        help="Live preview of the chart palette.",
    )

    @api.depends("graph_color_1", "graph_color_2", "graph_color_3", "graph_color_4")
    def _compute_graph_color_preview(self):
        colors = [
            color
            for color in (
                self.graph_color_1,
                self.graph_color_2,
                self.graph_color_3,
                self.graph_color_4,
            )
            if color
        ]
        if not colors:
            self.graph_color_preview = False
            return
        swatches = "".join(
            f'<div style="display:inline-block;width:48px;height:48px;'
            f"background:{color};border-radius:6px;margin:0 6px 6px 0;"
            f'border:1px solid rgba(0,0,0,0.2);"></div>'
            for color in colors
        )
        self.graph_color_preview = (
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">'
            f"{swatches}</div>"
        )

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]):
            raise models.ValidationError(
                _("Only one KpiTen configuration record is allowed.")
            )
        return super().create(vals_list)

    @api.model
    def get_config_json(self):
        """Chart default styling as expected by the dashboard apps.

        i.e. {"graph": {"layout": {"colorway": ["#00dc82", "#34cdfe"]}}}
        """
        rec = self.search([], limit=1)
        if not rec:
            return {}
        colorway = [
            color
            for color in (
                rec.graph_color_1,
                rec.graph_color_2,
                rec.graph_color_3,
                rec.graph_color_4,
            )
            if color
        ]
        layout = {}
        if colorway:
            layout["colorway"] = colorway
        if rec.graph_title_font_color:
            layout["title"] = {"font": {"color": rec.graph_title_font_color}}
        return {"graph": {"layout": layout}} if layout else {}
