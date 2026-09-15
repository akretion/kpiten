from odoo import _, api, fields, models

NUM_COLORS = 4


class KtConfig(models.Model):
    """
    One record only : the form view
    The configuration page in old way
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
        help="First hex color of the chart colorway (e.g. #00dc82).",
    )
    graph_color_2 = fields.Char(
        string="Color 2",
        help="Second hex color of the chart colorway.",
    )
    graph_color_3 = fields.Char(
        string="Color 3",
        help="Third hex color of the chart colorway.",
    )
    graph_color_4 = fields.Char(
        string="Color 4",
        help="Fourth hex color of the chart colorway.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]):
            raise models.ValidationError(
                _("Only one KpiTen configuration record is allowed.")
            )
        return super().create(vals_list)
