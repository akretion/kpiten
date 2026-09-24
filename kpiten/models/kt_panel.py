from odoo import api, fields, models


class KtPanel(models.Model):
    _name = "kt.panel"
    _description = "KPI Panel"
    _order = "sequence, id"

    name = fields.Char(required=True)
    # never empty : Postgres puts an empty sequence last, after "Main" (50)
    sequence = fields.Integer(default=10)
    description = fields.Char()
    # Filters available on the dashboard, as JSON
    # e.g. {"date": {"field": "date_order"}, "dimensions": [{"name": "user_id", "label": "Salesperson"}]}
    filter_config = fields.Text(default="{}")
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        comodel_name="kt.dataset.line", inverse_name="panel_id"
    )

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_view_lines(self):
        """The tiles (`kt.dataset.line`) of this dataset, in a list."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tiles of %s") % self.display_name,
            "res_model": "kt.dataset.line",
            "view_mode": f"{LIST},form",
            "domain": [("dataset_id", "=", self.id)],
            # the archived tiles are listed too, `active` tells them apart
            "context": {"default_dataset_id": self.id, "active_test": False},
        }
