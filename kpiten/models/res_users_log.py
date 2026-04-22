import uuid

from odoo import fields, models


class ResUsersLog(models.Model):
    _inherit = "res.users.log"

    uuid = fields.Char(compute="_compute_uuid", store=True)

    def _compute_uuid(self):
        for rec in self:
            rec.uuid = str(uuid.uuid4())
