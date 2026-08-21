import logging
from datetime import datetime, timedelta

from odoo import models

_logger = logging.getLogger(__name__)


class KpitenDemo(models.Model):
    _name = "kpiten.demo"
    _description = "KPI Ten Demo Data Generator"

    def _get_demo_partner(self, name):
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create(
                {
                    "name": name,
                    "is_company": False,
                    "customer_rank": 1,
                    "supplier_rank": 1,
                }
            )
        return partner

    def _get_demo_product(self):
        product = self.env["product.product"].search(
            [("is_storable", "=", True)], limit=1
        )
        if not product:
            product = self.env["product.product"].create(
                {
                    "name": "Demo Product",
                    "type": "consu",
                    "is_storable": True,
                    "list_price": 100.0,
                    "standard_price": 50.0,
                }
            )
        return product

    def _create_salesperson(self, name):
        user = self.env["res.users"].search([("name", "=", name)], limit=1)
        if user:
            return user

        login = name.lower().replace(" ", ".")
        return self.env["res.users"].create(
            {
                "name": name,
                "login": login,
                "email": f"{login}@example.com",
                "groups_id": [
                    (6, 0, [self.env.ref("base.group_user").id]),
                ],
            }
        )

    def generate_demo_data(self):
        """Generate demo sales, purchase and stock data across past years."""
        self.ensure_one()

        lara = self._create_salesperson("Lara Cleyte")
        jim = self._create_salesperson("Jim Nastic")
        salespeople = [lara, jim]

        partner_a = self._get_demo_partner("Demo Customer")
        partner_b = self._get_demo_partner("Demo Supplier")
        product = self._get_demo_product()

        today = datetime.now()
        years_offsets = [3, 2, 1]

        for offset in years_offsets:
            base_date = (today - timedelta(days=365 * offset)).replace(
                month=1, day=1, hour=10, minute=0, second=0
            )

            for month in range(1, 13):
                order_date = base_date.replace(month=month, day=1)
                salesperson = salespeople[(month + offset) % 2]

                # Sales order: create directly as confirmed so that
                # date_order keeps the historical value (action_confirm
                # overrides it with the current timestamp).
                self.env["sale.order"].create(
                    {
                        "partner_id": partner_a.id,
                        "user_id": salesperson.id,
                        "date_order": order_date,
                        "state": "sale",
                        "order_line": [
                            (
                                0,
                                0,
                                {
                                    "product_id": product.id,
                                    "product_uom_qty": month + offset,
                                    "price_unit": 100.0,
                                },
                            )
                        ],
                    }
                )

                # Purchase order: create directly as confirmed to avoid
                # triggering full purchase flows.
                self.env["purchase.order"].create(
                    {
                        "partner_id": partner_b.id,
                        "user_id": salesperson.id,
                        "date_order": order_date,
                        "date_planned": order_date,
                        "state": "purchase",
                        "order_line": [
                            (
                                0,
                                0,
                                {
                                    "product_id": product.id,
                                    "product_qty": month + offset,
                                    "price_unit": 50.0,
                                },
                            )
                        ],
                    }
                )

                _logger.info(
                    "Generated demo data for %s-%s", order_date.year, month
                )

        return True
