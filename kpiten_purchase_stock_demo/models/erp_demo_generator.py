import logging
import random
from datetime import timedelta

from odoo import fields, models

from odoo.addons.erp_demo_generator.models.erp_demo_generator import (
    DEMO_BATCH_SIZE,
    PRODUCTS,
    ROLE_BUYER,
    VENDOR_NAMES,
    demo_names,
)

_logger = logging.getLogger(__name__)

# more vendors than erp_demo_generator's 4, for richer "spend by vendor" charts
EXTRA_VENDOR_NAMES = [
    "Ateliers du Nord",
    "Comptoir des matériaux",
    "Distrib'Pro",
    "Euro Fournitures",
    "Maison Lefèvre & fils",
    "Quincaillerie Centrale",
]

PURCHASE_STATES = ["draft", "sent", "to approve", "cancel", "purchase", "done"]
PURCHASE_STATE_WEIGHTS = [0.04, 0.06, 0.02, 0.03, 0.55, 0.30]

# purchase.order columns forced in SQL : {column: SQL type}. effective_date
# and receipt_status come from purchase_stock.
ORDER_COLUMNS = {
    "state": "varchar",
    "date_approve": "timestamp",
    "effective_date": "timestamp",
    "receipt_status": "varchar",
    "invoice_status": "varchar",
    "create_date": "timestamp",
}
LINE_COLUMNS = {
    "state": "varchar",
    "qty_received": "numeric",
    "qty_invoiced": "numeric",
    "create_date": "timestamp",
}


class ErpDemoPurchaseStock(models.Model):
    _inherit = "erp.demo.generator"

    def _demo_steps(self):
        return [
            *super()._demo_steps(),
            ("purchase orders", self.generate_purchase_stock_demo),
        ]

    def _plan_purchase(self, rng, now, date_start):
        """Draw the lifecycle of one purchase order.

        Returns a dict : state, create_date, deadline (date_order),
        date_approve, date_planned (expected arrival), effective_date (actual
        arrival), receipt_status, invoice_status, received (received share).
        """
        state = rng.choices(PURCHASE_STATES, PURCHASE_STATE_WEIGHTS)[0]
        plan = {
            "state": state,
            "date_approve": None,  # None (NULL in SQL), not False
            "effective_date": None,
            "receipt_status": None,
            "invoice_status": "no",
            "received": 0,
        }
        if state in ("draft", "sent", "to approve"):
            # open RFQs are recent. Some sent RFQs have a future deadline
            # ("waiting"), the others are "late".
            create_date = now - timedelta(days=rng.uniform(0, 45))
            plan["create_date"] = create_date
            plan["date_planned"] = create_date + timedelta(days=rng.randint(7, 21))
            if state == "sent" and rng.random() < 0.4:
                plan["deadline"] = now + timedelta(days=rng.randint(1, 14))
            else:
                plan["deadline"] = create_date + timedelta(days=rng.randint(3, 10))
            return plan

        create_date = date_start + timedelta(
            seconds=rng.uniform(0, (now - date_start).total_seconds())
        )
        plan["create_date"] = create_date
        plan["deadline"] = create_date + timedelta(days=rng.randint(3, 10))
        if state == "cancel":
            plan["date_planned"] = create_date + timedelta(days=rng.randint(7, 21))
            return plan

        # confirmed : 0 to 6 days to confirm (usually short)
        date_approve = create_date + timedelta(days=min(6, rng.expovariate(1 / 1.5)))
        date_approve = min(date_approve, now)
        date_planned = date_approve + timedelta(days=rng.randint(3, 21))
        plan["date_approve"] = date_approve
        plan["date_planned"] = date_planned

        # receipt : ~70% on time (or early), the others 1 to 10 days late ;
        # otherwise the order is still waiting for its receipt.
        if rng.random() < 0.7:
            arrival = date_planned + timedelta(days=rng.randint(-3, 0))
        else:
            arrival = date_planned + timedelta(days=rng.randint(1, 10))
        if rng.random() < 0.88 and arrival <= now:
            plan["effective_date"] = arrival
            plan["receipt_status"] = "full"
            plan["received"] = 1
            plan["invoice_status"] = "invoiced" if rng.random() < 0.7 else "to invoice"
        elif rng.random() < 0.15 and date_planned <= now:
            plan["effective_date"] = date_planned
            plan["receipt_status"] = "partial"
            plan["received"] = 0.5
            plan["invoice_status"] = "to invoice"
        else:
            plan["receipt_status"] = "pending"
        return plan

    def _purchase_order_vals(self, rng, plan, buyer, vendors, products):
        return {
            "partner_id": rng.choice(vendors).id,
            "user_id": buyer.id,
            "date_order": plan["deadline"],
            "date_planned": plan["date_planned"],
            "order_line": [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_qty": rng.randint(1, 50),
                        "price_unit": round(
                            product.standard_price * rng.uniform(0.9, 1.2), 2
                        ),
                        "date_planned": plan["date_planned"],
                    },
                )
                for product in rng.sample(products, rng.randint(1, 3))
            ],
        }

    def _force_purchase_lifecycle(self, orders, plans):
        """Write state, dates and receipt/invoice statuses in SQL : no real
        receipts nor vendor bills are created (fast, dashboard-oriented)."""
        self._bulk_update(
            "purchase_order",
            ORDER_COLUMNS,
            [(o.id, *(p[c] for c in ORDER_COLUMNS)) for o, p in zip(orders, plans)],
        )
        self._bulk_update(
            "purchase_order_line",
            LINE_COLUMNS,
            [
                (
                    line.id,
                    p["state"],
                    line.product_qty * p["received"],
                    line.product_qty if p["invoice_status"] == "invoiced" else 0,
                    p["create_date"],
                )
                for o, p in zip(orders, plans)
                for line in o.order_line
            ],
        )

    def generate_purchase_stock_demo(self, n_purchases=3000, years=3, seed=42):
        """Purchase orders spread over `years`, placed by the buyer.

        Reuses erp_demo_generator's products and vendors (plus a few extra
        vendors). `seed` makes the dataset reproducible.
        """
        self.ensure_one()
        rng = random.Random(seed)
        now = fields.Datetime.now()
        date_start = now - timedelta(days=365 * years)

        buyer_name = demo_names(ROLE_BUYER)[0]
        buyer = self.env["res.users"].search([("name", "=", buyer_name)], limit=1)
        if not buyer:
            _logger.warning("buyer %s not found : orders are not assigned", buyer_name)
        vendors = [
            self._get_demo_partner(name) for name in VENDOR_NAMES + EXTRA_VENDOR_NAMES
        ]
        products = [self._create_product(*product) for product in PRODUCTS]

        # silent context : no mail tracking, much faster creations
        purchase_order = self.env["purchase.order"].with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_create_nosubscribe=True,
        )
        created = 0
        while created < n_purchases:
            size = min(DEMO_BATCH_SIZE, n_purchases - created)
            plans = [self._plan_purchase(rng, now, date_start) for _ in range(size)]
            orders = purchase_order.create(
                [
                    self._purchase_order_vals(rng, plan, buyer, vendors, products)
                    for plan in plans
                ]
            )
            # stored computed fields (receipt_status...) are recomputed on
            # flush : force it BEFORE the SQL, or it would overwrite it.
            self.env.flush_all()
            self._force_purchase_lifecycle(orders, plans)
            self.env.invalidate_all()
            created += size
            _logger.info("demo purchases : %s/%s", created, n_purchases)
        return created
