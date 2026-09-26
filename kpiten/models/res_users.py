from odoo import fields, models

from .kt_config import THEMES


class ResUsers(models.Model):
    _inherit = "res.users"

    # the theme of the dashboard apps the user chose (`kt.user.theme`) : in the apps,
    # or in their preferences here ; empty : the default theme of `kt.config`
    kpiten_theme = fields.Selection(
        THEMES,
        string="Dashboard theme",
        compute="_compute_kpiten_theme",
        inverse="_inverse_kpiten_theme",
        help="The colors of the KpiTen dashboards (Shiny, NiceGUI) ; empty : the "
        "default theme of the KpiTen configuration.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["kpiten_theme"]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ["kpiten_theme"]

    def _compute_kpiten_theme(self):
        lines = self.env["kt.user.theme"].sudo().search([("user_id", "in", self.ids)])
        themes = {line.user_id.id: line.theme for line in lines}
        for rec in self:
            rec.kpiten_theme = themes.get(rec.id, False)

    def _inverse_kpiten_theme(self):
        config = self.env["kt.config"].sudo()
        for rec in self:
            config.set_user_theme(rec.id, rec.kpiten_theme or False)
