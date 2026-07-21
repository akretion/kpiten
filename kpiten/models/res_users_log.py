import uuid

from odoo import fields, models, api


class ResUsersLog(models.Model):
    _inherit = "res.users.log"

    uuid = fields.Char(default=lambda self: str(uuid.uuid4()))

    # uuid = fields.Char(compute="_compute_uuid", store=True)

    # @api.depends()
    # def _compute_uuid(self):
    #     for rec in self:
    #         rec.uuid = str(uuid.uuid4())
