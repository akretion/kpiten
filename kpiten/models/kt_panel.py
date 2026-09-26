from odoo import _, api, fields, models

from ..compat import LIST, sql_constraints


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
    # the KPIs of the panel, each at its place (a KPI may be on several panels)
    tile_ids = fields.One2many(comodel_name="kt.panel.tile", inverse_name="panel_id")
    line_count = fields.Integer(
        compute="_compute_line_count",
        help="Number of tiles of this panel, the archived KPIs included.",
    )

    @api.depends("tile_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.tile_ids)

    def action_new_tile(self):
        """The tile builder on a new tile of this panel."""
        self.ensure_one()
        dataset = self.tile_ids[:1].kpi_id.dataset_id or self.env["kt.dataset"].search(
            [], limit=1
        )
        return self.env["kt.kpi.builder"].open_builder(
            {"name": _("New tile"), "dataset_id": dataset.id, "panel_id": self.id}
        )

    def action_view_lines(self):
        """The KPIs (`kt.kpi`) of this panel, in a list."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tiles of %s") % self.display_name,
            "res_model": "kt.kpi",
            "view_mode": f"{LIST},form",
            "domain": [("panel_ids", "in", self.id)],
            # the archived tiles are listed too, `active` tells them apart
            "context": {"active_test": False},
        }

    # -- the edit mode of the dashboards : a tile is a KPI of the panel -------------
    def _tiles_of(self, kpi_ids):
        self.ensure_one()
        return self.tile_ids.filtered(lambda t: t.kpi_id.id in kpi_ids)

    def remove_tiles(self, kpi_ids):
        """Take KPIs off the panel ; the KPIs are kept (the catalogue)."""
        self._tiles_of(kpi_ids).unlink()
        return True

    def set_tile_layout(self, kpi_id, col_span, tile_height):
        self._tiles_of([kpi_id]).write(
            {"col_span": col_span, "tile_height": tile_height}
        )
        return True

    def set_tile_order(self, kpi_ids):
        """The place of the KPIs on the panel : their index in `kpi_ids`."""
        tiles = {t.kpi_id.id: t for t in self._tiles_of(kpi_ids)}
        for sequence, kpi_id in enumerate(kpi_ids):
            if kpi_id in tiles:
                tiles[kpi_id].sequence = sequence
        return True


class KtPanelTile(models.Model):
    """A KPI on a panel : its place and its size there. The same KPI may be on
    several panels, each with its own layout."""

    _name = "kt.panel.tile"
    _description = "KPI on a panel"
    _order = "sequence, id"

    panel_id = fields.Many2one(
        comodel_name="kt.panel", required=True, ondelete="cascade", index=True
    )
    kpi_id = fields.Many2one(
        comodel_name="kt.kpi", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer()
    col_span = fields.Integer(
        default=1,
        help="Number of grid columns spanned by the tile",
    )
    tile_height = fields.Integer(
        default=320,
        help="Height of the tile in pixels",
    )
    name = fields.Char(related="kpi_id.name")
    kind = fields.Selection(related="kpi_id.kind")
    kpi_active = fields.Boolean(related="kpi_id.active", string="Active")

    sql_constraints(
        locals(),
        kpi_once_per_panel=(
            "UNIQUE(panel_id, kpi_id)",
            "A KPI is only once on a panel.",
        ),
    )
