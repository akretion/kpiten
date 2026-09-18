from odoo import models


class Kt(models.AbstractModel):
    _inherit = "kt"

    def _follow_relational_fields(self):
        """Also extract the date of the order on its lines (`order_id.date_order`).

        The Period filter of the Sales panel is on `date_order` : without this
        column on `sale.order.line`, a tile on the lines (top products...) would
        ignore the period.
        """
        fields = super()._follow_relational_fields()
        return {**fields, "sale.order": {"date_order"}}
