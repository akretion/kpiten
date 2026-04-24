from odoo import fields, models


class KpitenConfig(models.Model):
    _inherit = "ir.model.fields"

    sequence = fields.Integer(default=99)
    # enabled = fields.Boolean(defa)
