from odoo import models


class Kt(models.AbstractModel):
    _inherit = "kt"

    def _follow_relational_fields(self):
        """Relational columns the Sales dashboard tables need, on top of kpiten's.

        - `sale.order.date_order` : reaches the order lines as `order_id.date_order`,
          the Period filter of the Sales panel is on the order date
        - `res.partner.country_id.name` : `partner_id.country_id.name` (Top Countries)
        - `product.product.categ_id.complete_name` : the category as Odoo shows it,
          with its path ("All / Saleable"), not the short name (Top Categories)
        """
        fields = super()._follow_relational_fields()

        def more(model, *paths):
            return set(fields.get(model, ())) | set(paths)

        return {
            **fields,
            "sale.order": more("sale.order", "date_order"),
            "res.partner": more("res.partner", "country_id.name"),
            "product.product": more("product.product", "categ_id.complete_name"),
        }
