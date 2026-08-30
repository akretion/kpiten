from odoo import fields, models


class KpitenPanel(models.Model):
    _name = "kpiten.panel"
    _description = "KPI Panel"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer()
    active = fields.Boolean(default=True)
    config_line_ids = fields.One2many(
        comodel_name="kpiten.config.line", inverse_name="panel_id"
    )