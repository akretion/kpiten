from odoo import models


class Kpiten(models.AbstractModel):
    _name = "kpiten"
    _description = "KpiTen methods"

    def _follow_relational_fields(self):
        """
        for walkable paths only (e.g : some_model.user_id.name)
        [destined to be consumed by odoo's mapped function]
        """
        res = super()._follow_relational_fields()
        res.update(
            {
                "account.analytic.account": {"name"},
                "account.move": {"name"},
                "account.move.line": {"name", "display_type", "price_subtotal"},
                "account.analytic.plan": {"name"},
            }
        )
        return res

    def _get_reverse_lookups(self):
        res = super()._get_reverse_lookups()
        res.update(
            {
                "mrp.workcenter.productivity": {
                    "user_id": {
                        "target_model": "hr.employee",
                        "target_link_field": "user_id",
                        "target_value_field": "employee_type",
                    },
                },
                "account.analytic.line": {
                    "employee_id": {
                        "target_model": "hr.employee",
                        "target_link_field": "user_id",
                        "target_value_field": "employee_type",
                    }
                },
            }
        )
        return res
