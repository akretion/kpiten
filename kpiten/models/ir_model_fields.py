from odoo import fields, models


class IrModelFields(models.Model):
    _inherit = "ir.model.fields"

    sequence = fields.Integer(default=99)
