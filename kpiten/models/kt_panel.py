from odoo import _, api, fields, models

from ..compat import LIST


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
    line_ids = fields.One2many(comodel_name="kt.kpi", inverse_name="panel_id")
    line_count = fields.Integer(
        compute="_compute_line_count",
        help="Number of tiles of this panel, the archived ones included.",
    )

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_new_tile(self):
        """The tile builder on a new tile of this panel."""
        self.ensure_one()
        dataset = self.line_ids[:1].dataset_id or self.env["kt.dataset"].search(
            [], limit=1
        )
        return self.env["kt.kpi.builder"].open_builder(
            {"name": _("New tile"), "dataset_id": dataset.id, "panel_id": self.id}
        )

    def action_view_lines(self):
        """The tiles (`kt.kpi`) of this dataset, in a list."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tiles of %s") % self.display_name,
            "res_model": "kt.kpi",
            "view_mode": f"{LIST},form",
            "domain": [("panel_id", "=", self.id)],
            # the archived tiles are listed too, `active` tells them apart
            "context": {"default_panel_id": self.id, "active_test": False},
        }
