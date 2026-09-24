from odoo import api, models

from .res_company import SERVICE_KEY

# the fronts of KpiTen : a menu each (data/fronts.xml), shown when their address is set
FRONTS = ("shiny", "nicegui", "marimo")
FRONT_KEYS = {SERVICE_KEY % front for front in FRONTS}


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if FRONT_KEYS & set(records.mapped("key")):
            self.env["kt"]._sync_front_menus()
        return records

    def write(self, vals):
        result = super().write(vals)
        if FRONT_KEYS & set(self.mapped("key")):
            self.env["kt"]._sync_front_menus()
        return result

    def unlink(self):
        fronts = FRONT_KEYS & set(self.mapped("key"))
        result = super().unlink()
        if fronts:
            self.env["kt"]._sync_front_menus()
        return result
