import logging
import random
import unicodedata
from datetime import date, datetime, timedelta

from odoo import Command as cmd
from odoo import models

_logger = logging.getLogger(__name__)

CUSTOMER_NAMES = [
    "Jurassic Pack",
    "Tea Panic",
    "Terma & Louise",
    "Barber Streisand",
]
VENDOR_NAMES = [
    "Boîte à outils inc.",
    "Tuyau fer & estrades",
    "Prestige gadgets",
    "Fabriks & cie",
]
SALESPERSONS = [
    "Lara CLEYTE",
    "Jim NASTIC",
    "Marie STOURNE",
    "Karl AHJUMIDE",
    "Andy VOJHANBON",
    "Camille HONNETE",
    "Amar DISSOIR",
    "Cécile HONXA",
]

PRODUCTS = [
    ("Redwood plank", 120.0, 70.0),
    ("Stainless bolt set", 15.0, 8.0),
    ("Ceramic mug XXL", 9.5, 4.2),
    ("Desk lamp arc", 45.0, 22.0),
    ("Copper pipe 2m", 28.0, 14.0),
    ("Marble tile set", 60.0, 31.0),
    ("Ergo chair pro", 249.0, 140.0),
    ("Standing desk oak", 399.0, 230.0),
    ("Ph roll 50m", 85.0, 47.0),
    ("Nail gun compact", 160.0, 99.0),
    ("Smart lock hub", 129.0, 74.0),
    ("Garden tool kit", 74.0, 39.0),
]


def demo_password(login):
    """First name of a `first.last` login, lowercase ASCII (`cécile.honxa` -> `cecile`)."""
    first = login.split(".")[0]
    return (
        unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode().lower()
    )


class ErpDemoGenerator(models.Model):
    _name = "erp.demo.generator"
    _description = "ERP Demo Data Generator"

    def _get_demo_partner(self, name, is_company=True):
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create(
                {
                    "name": name,
                    "is_company": is_company,
                    "customer_rank": 1,
                    "supplier_rank": 1,
                }
            )
        return partner

    def _create_product(self, name, list_price, standard_price):
        product = self.env["product.product"].search([("name", "=", name)], limit=1)
        if not product:
            product = self.env["product.product"].create(
                {
                    "name": name,
                    "type": "consu",
                    "list_price": list_price,
                    "standard_price": standard_price,
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
                "password": demo_password(login),
                "groups_id": [
                    (6, 0, [self.env.ref("base.group_user").id]),
                ],
            }
        )

    def _set_create_date(self, records, dt):
        """Force create_date to `dt` via SQL.

        The ORM only lets `create()`/`write()` set create_date when running
        as superuser during module installation (`pool.ready` False) — see
        `BaseModel._prepare_create_values`. That doesn't hold once the
        module is installed (button re-run, `erp_demo_data_full`, or any
        real database), so create_date silently falls back to "now". Direct
        SQL works unconditionally.
        """
        if not records:
            return
        self.env.cr.execute(
            f'UPDATE "{records._table}" SET create_date = %s WHERE id IN %s',
            (dt, tuple(records.ids)),
        )
        records.invalidate_recordset(["create_date"])

    def _setup_demo_access_rights(self, salespeople):
        """Login of demo users = first.last, password = first name (lowercase ASCII) ; salespeople see only
        their own sales orders, Camille HONNETE all of them, Andy VOJHANBON
        is the only buyer (purchase user)."""

        def ref(xmlid):
            return self.env.ref(xmlid).id

        group_sale_own = ref("sales_team.group_sale_salesman")
        group_sale_all = ref("sales_team.group_sale_salesman_all_leads")
        group_purchase = ref("purchase.group_purchase_user")

        for user in salespeople:
            groups = [
                g.id
                for g in user.groups_id
                if g.id not in (group_sale_own, group_sale_all, group_purchase)
            ]
            if user.name == "Camille HONNETE":
                groups.append(group_sale_all)
            elif user.name == "Andy VOJHANBON":
                groups.append(group_purchase)
            else:
                groups.append(group_sale_own)
            user.write(
                {
                    "password": demo_password(user.login),
                    "groups_id": [(6, 0, groups)],
                }
            )

    # ---- sales : SO confirmed + customer invoice posted ----------------
    def _create_sale_full_cycle(self, order_date, salesperson, partner, product, qty):
        """Confirmed SO (+ customer invoice posted when possible)."""
        so = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "user_id": salesperson.id,
                "date_order": order_date,
                "state": "sale",
                "order_line": [
                    cmd.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "price_unit": product.list_price,
                        }
                    )
                ],
            }
        )
        self._set_create_date(so, order_date)
        self._set_create_date(so.order_line, order_date)
        invoice = self._create_customer_invoice(so, order_date)
        return {"sale_order": so, "invoice": invoice}

    def _create_customer_invoice(self, sale_order, order_date):
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": sale_order.partner_id.id,
            "invoice_date": order_date,
            "date": order_date,
            "invoice_origin": sale_order.name,
            "invoice_line_ids": [
                cmd.create(
                    {
                        "product_id": line.product_id.id,
                        "name": line.product_id.display_name,
                        "quantity": line.product_uom_qty,
                        "price_unit": line.price_unit,
                    }
                )
                for line in sale_order.order_line
            ],
        }
        invoice = self.env["account.move"].create(invoice_vals)
        self._set_create_date(invoice, order_date)
        self._set_create_date(invoice.invoice_line_ids, order_date)
        try:
            invoice.action_post()
        except Exception as err:
            _logger.warning("invoice post failed for %s : %s", sale_order.name, err)
            return None
        return invoice

    # ---- purchase : PO confirmed + receipt validated + bill posted -----
    def _create_purchase_full_cycle(self, order_date, partner, product, qty):
        po = self.env["purchase.order"].create(
            {
                "partner_id": partner.id,
                "date_order": order_date,
                "date_planned": order_date,
                "state": "purchase",
                "order_line": [
                    cmd.create(
                        {
                            "product_id": product.id,
                            "product_qty": qty,
                            "price_unit": product.standard_price,
                        }
                    )
                ],
            }
        )
        self._set_create_date(po, order_date)
        self._set_create_date(po.order_line, order_date)
        self._set_create_date(po.picking_ids, order_date)
        self._set_create_date(po.picking_ids.move_ids, order_date)
        receipt = self._validate_receipt(po)
        bill = self._create_vendor_bill(po, order_date)
        return {"purchase_order": po, "receipt": receipt, "bill": bill}

    def _validate_receipt(self, purchase_order):
        picking = purchase_order.picking_ids.filtered(lambda p: p.state != "cancel")[:1]
        if not picking:
            return None
        try:
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()
        except Exception as err:
            _logger.warning("receipt failed for %s : %s", purchase_order.name, err)
            return None
        return picking

    def _create_vendor_bill(self, purchase_order, order_date):
        invoice_vals = {
            "move_type": "in_invoice",
            "partner_id": purchase_order.partner_id.id,
            "invoice_date": order_date,
            "date": order_date,
            "invoice_origin": purchase_order.name,
            "invoice_line_ids": [
                cmd.create(
                    {
                        "product_id": line.product_id.id,
                        "name": line.product_id.display_name,
                        "quantity": line.product_qty,
                        "price_unit": line.price_unit,
                    }
                )
                for line in purchase_order.order_line
            ],
        }
        bill = self.env["account.move"].create(invoice_vals)
        self._set_create_date(bill, order_date)
        self._set_create_date(bill.invoice_line_ids, order_date)
        try:
            bill.action_post()
        except Exception as err:
            _logger.warning("bill post failed for %s : %s", purchase_order.name, err)
            return None
        return bill

    def generate_demo_data(self, months: int = 12):
        """Generate a demo data set of 12 products over the last `months` :
        default 12 months (full history) ; light install uses 2 months:
        - sold (SO confirmed) and invoiced (customer invoice posted)
        - purchased (PO confirmed), received (receipt validated) and
          vendor-billed
        """
        self.ensure_one()
        today = date.today()
        random.seed(42)
        # `months` controls the volume : 2 months ≈ 15 % of the full set
        # (12 months), full data is provided by erp_demo_data_full.

        products = [
            self._create_product(name, list_price, standard_price)
            for name, list_price, standard_price in PRODUCTS
        ]
        customers = [self._get_demo_partner(name) for name in CUSTOMER_NAMES]
        vendors = [self._get_demo_partner(name) for name in VENDOR_NAMES]
        salespeople = [self._create_salesperson(name) for name in SALESPERSONS]
        self._setup_demo_access_rights(salespeople)

        generated = 0
        for month_offset in range(months):
            day = today - timedelta(days=30 * month_offset)
            order_date = datetime(
                year=day.year,
                month=day.month,
                day=1,
                hour=10,
                minute=0,
                second=0,
            )
            for product in PRODUCTS:
                product_id = self.env["product.product"].search(
                    [("name", "=", product[0])], limit=1
                )
                qty = random.randint(2, 12)
                self._create_sale_full_cycle(
                    order_date,
                    random.choice(salespeople),
                    random.choice(customers),
                    product_id,
                    qty,
                )
                self._create_purchase_full_cycle(
                    order_date, random.choice(vendors), product_id, qty
                )
                generated += 2
                _logger.info(
                    "demo month %s product %s : sale + purchase",
                    order_date,
                    product_id.name,
                )
        _logger.info("demo data done : %s documents", generated)
        return True
