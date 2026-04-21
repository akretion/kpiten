from odoo import fields, models


class KpitenConfig(models.Model):
    _name = "kpiten.config"
    _description = "Configuration for kpiten"

    name = fields.Char(required=True)
    state = fields.Selection(selection=[("draft", "Draft"), ("validated", "Validated")])
    line_ids = fields.One2many(
        comodel_name="kpiten.config.line", inverse_name="config_id"
    )
    model_ids = fields.Many2many(
        comodel_name="ir.model", help="Models used to produce dataframe"
    )
    company_id = fields.Many2one(comodel_name="res.company")


class KpitenConfigLine(models.Model):
    _name = "kpiten.config.line"
    _description = "Configuration lines for kpiten"

    config_id = fields.Many2one(comodel_name="kpiten.config", required=True)
    definition = fields.Text(help="Store settings for kpi")
    active = fields.Boolean(default=True)
