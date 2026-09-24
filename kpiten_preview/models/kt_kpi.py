from odoo import _, models


class KtDatasetLine(models.Model):
    _inherit = "kt.kpi"

    def action_preview(self):
        """Open the preview of the tile."""
        self.ensure_one()
        wizard = self.env["kt.kpi.preview"].create({"line_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Preview of %s") % (self.name or self.kind),
            "res_model": "kt.kpi.preview",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }
