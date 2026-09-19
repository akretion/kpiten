from odoo import models


class KtDatasetLine(models.Model):
    _inherit = "kt.dataset.line"

    def action_preview(self):
        """Open the preview of the tile."""
        self.ensure_one()
        wizard = self.env["kt.dataset.line.preview"].create({"line_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Preview of %s", self.name or self.kind),
            "res_model": "kt.dataset.line.preview",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }
