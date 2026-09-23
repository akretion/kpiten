import logging
import random
from datetime import timedelta

from odoo import fields, models

from .world import (
    MEDIUMS,
    SOURCES,
    ZONE_WEIGHTS,
    ZONES,
    seasonal_date,
    weighted,
)
from .erp_demo_generator import (
    CUSTOMER_NAMES,
    DEMO_BATCH_SIZE,
    PRODUCTS,
    ROLE_SALES_MANAGER,
    ROLE_SELLER,
    demo_names,
)

_logger = logging.getLogger(__name__)

# more customers than erp_demo_generator's 4, for richer "sales by customer" charts
EXTRA_COMPANY_NAMES = [
    "Atelier Dubois",
    "Brasserie du Port",
    "Cabinet Lambert & associés",
    "Domaine des Lilas",
    "Ets Marchand",
    "Fromagerie Roussel",
    "Garage de la Gare",
    "Hôtel Beau Rivage",
    "Imprimerie Moderne",
    "Jardineries Vertes",
    "Librairie du Centre",
    "Menuiserie Perrin",
    "Nettoyage Express",
    "Optique Saint-Michel",
    "Pâtisserie Girard",
    "Résidence Les Cèdres",
]
EXTRA_PERSON_NAMES = [
    "Alice Moreau",
    "Bruno Lefebvre",
    "Chloé Garnier",
    "David Faure",
    "Élodie Blanc",
    "François Mercier",
    "Gaëlle Robin",
    "Hugo Chevalier",
    "Inès Fontaine",
    "Julien Roger",
]

SALE_STATES = ["draft", "sent", "cancel", "sale"]
SALE_STATE_WEIGHTS = [0.06, 0.08, 0.03, 0.83]

# sale.order columns forced in SQL : {column: SQL type}. delivery_status and
# effective_date come from sale_stock.
ORDER_COLUMNS = {
    "state": "varchar",
    "invoice_status": "varchar",
    "delivery_status": "varchar",
    "effective_date": "timestamp",
    "create_date": "timestamp",
}
LINE_COLUMNS = {
    "state": "varchar",
    "invoice_status": "varchar",
    "qty_delivered": "numeric",
    "qty_invoiced": "numeric",
    "qty_to_invoice": "numeric",
    "create_date": "timestamp",
}


class ErpDemoSaleStock(models.Model):
    _inherit = "erp.demo.generator"

    def _demo_steps(self):
        return [*super()._demo_steps(), ("sales orders", self.generate_sale_stock_demo)]

    def _plan_sale(self, rng, now, date_start):
        """Draw the lifecycle of one sales order.

        Returns a dict : state, create_date (= date_order), commitment_date
        (promised delivery), effective_date (actual delivery), delivery_status,
        invoice_status, delivered (delivered share), invoiced (bool).
        """
        state = rng.choices(SALE_STATES, SALE_STATE_WEIGHTS)[0]
        plan = {
            "state": state,
            "commitment_date": None,  # None (NULL in SQL), not False
            "effective_date": None,
            "delivery_status": None,
            "invoice_status": "no",
            "delivered": 0,
            "invoiced": False,
        }
        if state in ("draft", "sent"):
            # open quotations are recent
            plan["create_date"] = now - timedelta(days=rng.uniform(0, 45))
            return plan

        # slightly growing activity, busier months (world.SEASON)
        plan["create_date"] = seasonal_date(rng, date_start, now)
        if state == "cancel":
            return plan

        create_date = plan["create_date"]
        commitment_date = create_date + timedelta(days=rng.randint(2, 14))
        plan["commitment_date"] = commitment_date

        # delivery : ~70% on time (or early), the others 1 to 7 days late ;
        # otherwise the order is still waiting for its delivery.
        if rng.random() < 0.7:
            delivery = commitment_date + timedelta(days=rng.randint(-2, 0))
        else:
            delivery = commitment_date + timedelta(days=rng.randint(1, 7))
        if rng.random() < 0.93 and delivery <= now:
            plan["effective_date"] = delivery
            plan["delivery_status"] = "full"
            plan["delivered"] = 1
            # only fully delivered orders can be fully invoiced
            plan["invoiced"] = rng.random() < 0.85 and delivery < now - timedelta(
                days=3
            )
        elif rng.random() < 0.3 and commitment_date <= now:
            plan["effective_date"] = commitment_date
            plan["delivery_status"] = "partial"
            plan["delivered"] = 0.5
        else:
            plan["delivery_status"] = "pending"
        plan["invoice_status"] = "invoiced" if plan["invoiced"] else "to invoice"
        return plan

    def _demo_customers(self):
        """erp_demo_generator's customers + extra ones (customers only : the
        inherited `_get_demo_partner` would also flag them as vendors)."""
        partner = self.env["res.partner"]
        names = CUSTOMER_NAMES + EXTRA_COMPANY_NAMES + EXTRA_PERSON_NAMES
        customers = partner.search([("name", "in", names)])
        existing = set(customers.mapped("name"))
        missing = [name for name in names if name not in existing]
        return customers | partner.create(
            [
                {
                    "name": name,
                    "is_company": name not in EXTRA_PERSON_NAMES,
                    "customer_rank": 1,
                }
                for name in missing
            ]
        )

    def _demo_salespeople(self):
        """The salespeople : the demo users whose role sells (this excludes the
        buyer)."""
        return self.env["res.users"].search(
            [("name", "in", demo_names(ROLE_SELLER, ROLE_SALES_MANAGER))]
        )

    def _sale_order_vals(self, rng, plan, salesperson, customer, products, deal):
        """`deal` : the team, the price list (its currency) and the channel of the
        order ; the prices are the list prices in the currency of the price list."""
        rate = self.demo_rate(deal["currency"], plan["create_date"])
        vals = {
            "partner_id": customer.id,
            "user_id": salesperson.id,
            "team_id": deal["team"].id,
            "pricelist_id": deal["pricelist"].id,
            "medium_id": deal["medium"].id,
            "source_id": deal["source"].id,
            "date_order": plan["create_date"],
            "order_line": [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_uom_qty": rng.randint(1, 12),
                        "price_unit": round(
                            product.list_price * rate * rng.uniform(0.95, 1.05), 2
                        ),
                    },
                )
                for product in rng.sample(products, rng.randint(1, 4))
            ],
        }
        if plan["commitment_date"]:
            vals["commitment_date"] = plan["commitment_date"]
        return vals

    def _force_sale_lifecycle(self, orders, plans):
        """Write state, delivery and invoicing statuses in SQL : no real
        deliveries nor customer invoices are created (fast,
        dashboard-oriented)."""
        self._bulk_update(
            "sale_order",
            ORDER_COLUMNS,
            [(o.id, *(p[c] for c in ORDER_COLUMNS)) for o, p in zip(orders, plans)],
        )
        self._bulk_update(
            "sale_order_line",
            LINE_COLUMNS,
            [
                (
                    line.id,
                    p["state"],
                    p["invoice_status"],
                    line.product_uom_qty * p["delivered"],
                    line.product_uom_qty if p["invoiced"] else 0,
                    (
                        0
                        if p["invoiced"] or p["state"] != "sale"
                        else line.product_uom_qty
                    ),
                    p["create_date"],
                )
                for o, p in zip(orders, plans)
                for line in o.order_line
            ],
        )

    def generate_sale_stock_demo(self, n_orders=10000, years=3, seed=42):
        """Sales orders spread over `years` and over the salespeople.

        Reuses erp_demo_generator's products and customers (plus extra
        customers). `seed` makes the dataset reproducible.
        """
        self.ensure_one()
        rng = random.Random(seed)
        now = fields.Datetime.now()
        date_start = now - timedelta(days=365 * years)

        # the world : each zone its customers, team, salespeople, price list
        teams = self._demo_teams()
        pricelists = self._demo_pricelists()
        by_zone = {}
        for partner, zone in self.demo_customers().items():
            by_zone.setdefault(zone, []).append(partner)
        zones = [z for z in ZONE_WEIGHTS if by_zone.get(z)]
        zone_weights = [ZONE_WEIGHTS[z] for z in zones]
        team_of = {z: teams[ZONES[z]["team"]] for z in zones}
        sellers = {
            z: list(team_of[z].member_ids) or list(self._demo_salespeople())
            for z in zones
        }
        # uneven activity between salespeople
        seller_weights = {z: [rng.uniform(0.6, 1.6) for _ in sellers[z]] for z in zones}
        mediums = {
            n: self.env["utm.medium"].search([("name", "=", n)], limit=1)
            for n, _w in MEDIUMS
        }
        sources = {
            n: self.env["utm.source"].search([("name", "=", n)], limit=1)
            for n, _w in SOURCES
        }
        products = [self._create_product(*product) for product in PRODUCTS]
        self = self.with_context(demo_rates={})  # the rate of a month, read once

        def deal(zone):
            return {
                "team": team_of[zone],
                "pricelist": pricelists[zone],
                "currency": ZONES[zone]["pricelist"][1],
                "medium": mediums[weighted(rng, MEDIUMS)],
                "source": sources[weighted(rng, SOURCES)],
            }

        # silent context : no mail tracking, much faster creations
        sale_order = self.env["sale.order"].with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_create_nosubscribe=True,
        )
        created = 0
        while created < n_orders:
            size = min(DEMO_BATCH_SIZE, n_orders - created)
            plans = [self._plan_sale(rng, now, date_start) for _ in range(size)]
            picks = [rng.choices(zones, zone_weights)[0] for _ in plans]
            orders = sale_order.create(
                [
                    self._sale_order_vals(
                        rng,
                        plan,
                        rng.choices(sellers[zone], seller_weights[zone])[0],
                        rng.choice(by_zone[zone]),
                        products,
                        deal(zone),
                    )
                    for plan, zone in zip(plans, picks)
                ]
            )
            # stored computed fields (delivery_status...) are recomputed on
            # flush : force it BEFORE the SQL, or it would overwrite it.
            self.env.flush_all()
            self._force_sale_lifecycle(orders, plans)
            self.env.invalidate_all()
            created += size
            _logger.info("demo sales : %s/%s", created, n_orders)
        return created
