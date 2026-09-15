from odoo import api, fields, models, _


class KtConfig(models.Model):
    """Chart / app defaults previously stored as the `kt_config` system param.

    One record only : the form view is the single entry point, with one field
    per key of the legacy json (`{"graph": {"layout": {...}}}`). Color fields
    render their swatch in the form.
    """

    _name = "kt.config"
    _description = "KpiTen configuration"

    graph_title_font_color = fields.Char(
        string="Graph title font color",
        help="Color of the chart title font (hex, e.g. #dbe4ef).",
    )
    graph_colorway = fields.Char(
        string="Graph colorway",
        help="Comma-separated hex colors used for the chart series.",
    )
    graph_colorway_preview = fields.Html(
        string="Colorway preview",
        compute="_compute_colorway_preview",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]):
            raise models.ValidationError(
                _("Only one KpiTen configuration record is allowed.")
            )
        return super().create(vals_list)

    @api.depends("graph_colorway")
    def _compute_colorway_preview(self):
        for rec in self:
            rec.graph_colorway_preview = self._colorway_html(rec.graph_colorway)

    @staticmethod
    def _colorway_html(value: str) -> str:
        """Render a comma-separated colorway as colored swatches."""
        colors = [c.strip() for c in (value or "").split(",") if c.strip()]
        if not colors:
            return ""
        spans = "".join(
            f'<span style="display:inline-block;width:28px;height:28px;'
            f"margin:2px;border-radius:4px;border:1px solid #ccc;"
            f'background:{c};" title="{c}"></span>'
            for c in colors
        )
        return f"<div>{spans}</div>"

    def get_config_json(self) -> dict:
        """Serialize the record back to the legacy `kt_config` json shape."""
        self.ensure_one()
        graph: dict = {"layout": {}}
        if self.graph_title_font_color:
            graph["layout"]["title_font_color"] = self.graph_title_font_color
        if self.graph_colorway:
            graph["layout"]["colorway"] = [
                c.strip() for c in self.graph_colorway.split(",") if c.strip()
            ]
        return {"graph": graph} if graph["layout"] else {}

    def ensure_single(self) -> "KtConfig":
        """Return the unique config record, creating it if missing."""
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({})
        return rec
