from odoo import fields, models


class KtPanel(models.Model):
    _name = "kt.panel"
    _description = "KPI Panel"
    _order = "sequence, id"

    name = fields.Char(required=True)
    # never empty : Postgres puts an empty sequence last, after "Main" (50)
    sequence = fields.Integer(default=10)
    description = fields.Char()
    # Filters available on the dashboard, as JSON
    # e.g. {"date": {"field": "date_order"}, "dimensions": [{"name": "user_id", "label": "Salesperson"}]}
    filter_config = fields.Text(default="{}")
    active = fields.Boolean(default=True)
    config_line_ids = fields.One2many(
        comodel_name="kt.dataset.line", inverse_name="panel_id"
    )
