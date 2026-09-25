from odoo import api, fields, models

from ..compat import get_param
from .res_company import SERVICE_KEY

# the fronts of KpiTen : a button each on the home page, shown when their address is set
FRONTS = ("shiny", "nicegui", "marimo")


class KtHome(models.TransientModel):
    """The home page of KpiTen (the action of its menu), open to every user : a button
    per front whose address is set (`kpiten_<front>_service`). Nothing on it needs
    more rights than those of an internal user."""

    _name = "kt.home"
    _description = "KpiTen home"

    name = fields.Char(default="KpiTen")  # the breadcrumb

    shiny_ok = fields.Boolean(compute="_compute_fronts")
    nicegui_ok = fields.Boolean(compute="_compute_fronts")
    marimo_ok = fields.Boolean(compute="_compute_fronts")

    def _compute_fronts(self):
        for home in self:
            for front in FRONTS:
                home[f"{front}_ok"] = bool(get_param(self.env, SERVICE_KEY % front))

    @api.model
    def action_home(self):
        """The home page : a record of its own, so that its buttons are computed and the
        breadcrumb reads « KpiTen » (a new record would say « New », with its save
        buttons)."""
        return {
            "type": "ir.actions.act_window",
            "name": "KpiTen",
            "res_model": "kt.home",
            "res_id": self.create({}).id,
            "view_mode": "form",
            "views": [(self.env.ref("kpiten.kt_home_form").id, "form")],
            "target": "current",
        }

    def _open(self, front: str):
        return self.env["kt"].action_redirect_to_kpiten(application=front)

    def action_open_shiny(self):
        return self._open("shiny")

    def action_open_nicegui(self):
        return self._open("nicegui")

    def action_open_marimo(self):
        return self._open("marimo")
