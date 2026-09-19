import logging
import math
import random
import time
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.erp_demo_generator.models.erp_demo_generator import PRODUCTS

_logger = logging.getLogger(__name__)

# marks (sale.order.origin) : the orders of this module, the throwaway templates
BIG_ORIGIN = "kpiten big demo"
TEMPLATE_ORIGIN = "kpiten big demo template"
CUSTOMER_REF = "big-demo"  # res.partner.ref of the customers of this module
PRODUCT_PREFIX = "BIG"  # product.default_code prefix
SILENT = {
    "tracking_disable": True,
    "mail_create_nolog": True,
    "mail_notrack": True,
    "mail_create_nosubscribe": True,
}

FIRST_NAMES = [
    "Alice", "Bruno", "Chloé", "David", "Élodie", "François", "Gaëlle", "Hugo",
    "Inès", "Julien", "Karine", "Louis", "Manon", "Nicolas", "Océane", "Pierre",
    "Quentin", "Rachel", "Sophie", "Thomas", "Ursule", "Victor", "Wendy",
    "Xavier", "Yasmine", "Zoé", "Adrien", "Béatrice", "Cédric", "Delphine",
    "Émile", "Florence", "Guillaume", "Hélène", "Ivan", "Julie", "Kévin",
    "Laura", "Mathieu", "Nadia",
]  # fmt: skip
LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit",
    "Durand", "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel",
    "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier", "Morel",
    "Girard", "André", "Mercier", "Dupont", "Lambert", "Bonnet", "François",
    "Martinez", "Legrand", "Garnier", "Faure", "Rousseau", "Blanc", "Guérin",
    "Muller", "Henry", "Roussel", "Nicolas", "Perrin",
]  # fmt: skip
COMPANY_KINDS = [
    "Atelier", "Brasserie", "Cabinet", "Domaine", "Entreprise", "Fromagerie",
    "Garage", "Hôtel", "Imprimerie", "Jardinerie", "Librairie", "Menuiserie",
    "Nettoyage", "Optique", "Pâtisserie", "Quincaillerie", "Résidence",
    "Serrurerie", "Transports", "Univers", "Verrerie", "Boulangerie", "Cave",
    "Distillerie", "Ébénisterie", "Fleuriste", "Graphique", "Horlogerie",
    "Institut", "Laiterie",
]  # fmt: skip
COMPANY_TAILS = [
    "Dubois", "du Port", "Lambert", "des Lilas", "Marchand", "Roussel",
    "de la Gare", "Beau Rivage", "Moderne", "Vertes", "du Centre", "Perrin",
    "Express", "Saint-Michel", "Girard", "des Cèdres", "Lefèvre", "Nord", "Sud",
    "Est", "Ouest", "Central", "Pro", "Plus", "Services", "& Fils", "& Cie",
    "Group", "France", "Europe",
]  # fmt: skip
PRODUCT_NOUNS = [
    "Planche", "Boulon", "Tuyau", "Carrelage", "Lampe", "Chaise", "Bureau",
    "Rouleau", "Cloueur", "Serrure", "Kit", "Peinture", "Câble", "Gants",
    "Casque", "Vis", "Écrou", "Rondelle", "Perceuse", "Scie", "Marteau",
    "Tournevis", "Pince", "Niveau", "Échelle", "Colle", "Vernis", "Prise",
    "Interrupteur", "Ampoule",
]  # fmt: skip
PRODUCT_ADJECTIVES = [
    "inox", "chêne", "compact", "pro", "renforcé", "léger", "XL", "mini",
    "premium", "standard", "étanche", "isolant", "universel", "double",
    "simple", "noir", "blanc", "gris", "rapide", "solide", "souple", "rigide",
    "large", "fin", "long", "court", "brut", "poli", "teinté", "mat",
]  # fmt: skip

ORDER_TEMP = """
CREATE TEMP TABLE _kt_big_order (
    order_id int, name varchar, partner_id int, user_id int, state varchar,
    create_date timestamp, validity_date date, commitment_date timestamp,
    effective_date timestamp, delivery_status varchar, invoice_status varchar,
    delivered numeric, invoiced boolean,
    amount_untaxed numeric, amount_tax numeric, amount_total numeric
)
"""
LINE_TEMP = """
CREATE TEMP TABLE _kt_big_line (
    line_id int, order_id int, line_no int, product_id int, tpl_line_id int,
    qty numeric, price_unit numeric, subtotal numeric, tax numeric,
    total numeric, reduce_inc numeric
)
"""


def _next_prime(number):
    """Smallest prime >= number. With a prime count of products, the products
    of an order (base + k * step, modulo the count) are all different."""

    def is_prime(k):
        return k > 1 and all(k % d for d in range(2, math.isqrt(k) + 1))

    while not is_prime(number):
        number += 1
    return number


def _customer_names():
    """(all the names in a fixed order, the subset that are companies)."""
    persons = [f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES]
    companies = [f"{kind} {tail}" for kind in COMPANY_KINDS for tail in COMPANY_TAILS]
    names = persons + companies
    random.Random(7).shuffle(names)
    return names, set(companies)


def _cents(amount_cents):
    return Decimal(amount_cents) / 100


def _tax_cents(subtotal_cents, rate):
    """Tax of a line, in cents : `rate` % of the subtotal, rounded half up like
    Odoo does."""
    if not rate:
        return 0
    return int((Decimal(subtotal_cents) * rate / 100).to_integral_value(ROUND_HALF_UP))


class ErpDemoSaleStockBig(models.Model):
    _inherit = "erp.demo.generator"

    def _demo_steps(self):
        return [
            *super()._demo_steps(),
            ("big sales orders", self.generate_big_sale_demo_install),
        ]

    # ---- reference data : customers, products, template orders ------------
    def _big_customers(self, n_customers):
        """`n_customers` customers of this module, created when missing."""
        names, companies = _customer_names()
        if n_customers > len(names):
            raise UserError(f"At most {len(names)} customers are supported.")
        partner = self.env["res.partner"].with_context(**SILENT)
        existing = partner.search([("ref", "=", CUSTOMER_REF)], order="id")
        missing = n_customers - len(existing)
        if missing > 0:
            taken = set(existing.mapped("name"))
            partner.create(
                [
                    {
                        "name": name,
                        "is_company": name in companies,
                        "customer_rank": 1,
                        "ref": CUSTOMER_REF,
                    }
                    for name in [n for n in names if n not in taken][:missing]
                ]
            )
        return partner.search(
            [("ref", "=", CUSTOMER_REF)], order="id", limit=n_customers
        )

    def _big_products(self, n_products):
        """The 12 products of erp_demo_generator plus extra ones, `n_products`
        rounded up to a prime number."""
        base = [self._create_product(*product) for product in PRODUCTS]
        total = _next_prime(max(n_products, len(base) + 2))
        codes = [f"{PRODUCT_PREFIX}{i:04d}" for i in range(1, total - len(base) + 1)]
        template = self.env["product.template"].with_context(**SILENT)
        existing = template.search([("default_code", "in", codes)])
        have = set(existing.mapped("default_code"))
        vals = []
        for i, code in enumerate(codes):
            if code in have:
                continue
            price = round(random.Random(i).uniform(5, 600), 2)
            noun = PRODUCT_NOUNS[i % len(PRODUCT_NOUNS)]
            adjective = PRODUCT_ADJECTIVES[
                (i // len(PRODUCT_NOUNS)) % len(PRODUCT_ADJECTIVES)
            ]
            vals.append(
                {
                    "name": f"{noun} {adjective} {code[len(PRODUCT_PREFIX):]}",
                    "default_code": code,
                    "type": "consu",
                    "sale_ok": True,
                    "purchase_ok": False,
                    "list_price": price,
                    "standard_price": round(price * 0.6, 2),
                }
            )
        if vals:
            template.create(vals)
        extras = template.search([("default_code", "in", codes)], order="default_code")
        return self.env["product.product"].browse(
            [p.id for p in base] + [t.product_variant_id.id for t in extras]
        )

    def _big_templates(self, products, customer):
        """Throwaway draft orders, made through the ORM, with a line for every
        product : the rows the bulk insert copies (all the columns, including
        those of other installed modules, get a valid value). Returns the
        orders and {product id: template line}."""
        order = self.env["sale.order"].with_context(**SILENT)
        order.search([("origin", "=", TEMPLATE_ORIGIN)]).unlink()  # interrupted run
        ids = products.ids
        vals = []
        for start in range(0, len(ids), 4):
            chunk = ids[start : start + 4]
            chunk += ids[: 4 - len(chunk)]  # the last order is completed
            vals.append(
                {
                    "partner_id": customer.id,
                    "origin": TEMPLATE_ORIGIN,
                    "order_line": [
                        (0, 0, {"product_id": pid, "product_uom_qty": 1})
                        for pid in chunk
                    ],
                }
            )
        orders = order.create(vals)
        self.env.flush_all()
        lines = {}
        for line in orders.order_line:
            lines.setdefault(line.product_id.id, line)
        return orders, lines

    def _big_tax_rate(self, line):
        """Total percentage of the taxes of a line : only percent taxes, not
        included in the price, are supported (what the amounts computation
        replicates)."""
        rate = Decimal(0)
        for tax in line.tax_id:
            included = (
                tax.price_include
                if "price_include" in tax._fields
                else tax.price_include_override == "tax_included"
            )
            if tax.amount_type != "percent" or included:
                raise UserError(
                    f"Unsupported tax '{tax.display_name}' on {line.product_id.display_name}"
                    " : only percent taxes, excluded from the price."
                )
            rate += Decimal(str(tax.amount))
        return rate

    # ---- sequences and SQL helpers -----------------------------------------
    def _big_order_sequence(self):
        """(postgres sequence, prefix, padding) of the sale order names."""
        sequence = self.env["ir.sequence"].search(
            [
                ("code", "=", "sale.order"),
                ("company_id", "in", [self.env.company.id, False]),
            ],
            limit=1,
        )
        prefix = sequence.prefix or ""
        if (
            sequence.implementation != "standard"
            or sequence.use_date_range
            or sequence.number_increment != 1
            or sequence.suffix
            or "%" in prefix
            or "$" in prefix
        ):
            raise UserError("The sale order sequence must be a plain 'standard' one.")
        return f"ir_sequence_{sequence.id:03d}", prefix, sequence.padding

    def _big_reserve(self, sequence, count):
        """Reserve `count` consecutive values of a postgres sequence, return
        the first one."""
        cr = self.env.cr
        cr.execute("SELECT nextval(%s)", (sequence,))
        first = cr.fetchone()[0]
        if count > 1:
            cr.execute("SELECT setval(%s, %s)", (sequence, first + count - 1))
        return first

    def _big_columns(self, table):
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return [row[0] for row in self.env.cr.fetchall()]

    def _big_clone(self, table, overrides, source):
        """INSERT INTO `table` all its columns, `overrides` {column: SQL
        expression} where given, else the value of the template row `t`.
        `source` is the FROM clause (with the template row aliased `t`)."""
        columns = self._big_columns(table)
        select = ", ".join(overrides.get(c, f't."{c}"') for c in columns)
        names = ", ".join(f'"{c}"' for c in columns)
        self.env.cr.execute(
            f'INSERT INTO "{table}" ({names}) SELECT {select} FROM {source}'
        )

    # ---- one batch : plan (python) -> temp tables -> bulk insert (SQL) ------
    def _big_batch(self, rng, now, date_start, size, ctx):
        cr = self.env.cr
        lines_per_order = ctx["lines_per_order"]
        first_order = self._big_reserve("sale_order_id_seq", size)
        first_line = self._big_reserve("sale_order_line_id_seq", size * lines_per_order)
        first_number = self._big_reserve(ctx["sequence"], size)
        prefix, padding = ctx["prefix"], ctx["padding"]
        pids, prices, tpl_lines, rates = (
            ctx["pids"],
            ctx["prices"],
            ctx["tpl_lines"],
            ctx["rates"],
        )
        count = len(pids)

        # the orders come in date order : names and ids grow with the date
        plans = sorted(
            (self._plan_sale(rng, now, date_start) for _ in range(size)),
            key=lambda plan: plan["create_date"],
        )
        order_rows, line_rows, order_ids = [], [], []
        for i, plan in enumerate(plans):
            order_id = first_order + i
            order_ids.append(order_id)
            # `lines_per_order` different products : base + k * step (mod prime)
            base, step = rng.randrange(count), 1 + rng.randrange(count - 1)
            untaxed = tax = 0
            for k in range(lines_per_order):
                index = (base + k * step) % count
                qty = rng.randint(1, 12)
                price = max(1, round(prices[index] * rng.uniform(0.95, 1.05) * 100))
                subtotal = qty * price
                line_tax = _tax_cents(subtotal, rates[index])
                untaxed += subtotal
                tax += line_tax
                line_rows.append(
                    (
                        first_line + i * lines_per_order + k,
                        order_id,
                        k + 1,
                        pids[index],
                        tpl_lines[index],
                        qty,
                        _cents(price),
                        _cents(subtotal),
                        _cents(line_tax),
                        _cents(subtotal + line_tax),
                        Decimal(str(round((subtotal + line_tax) / qty / 100, 2))),
                    )
                )
            created = plan["create_date"]
            order_rows.append(
                (
                    order_id,
                    f"{prefix}{str(first_number + i).zfill(padding)}",
                    rng.choice(ctx["customer_ids"]),
                    rng.choices(ctx["seller_ids"], ctx["weights"])[0],
                    plan["state"],
                    created,
                    (created + timedelta(days=30)).date(),  # quotation validity
                    plan["commitment_date"],
                    plan["effective_date"],
                    plan["delivery_status"],
                    plan["invoice_status"],
                    Decimal(str(plan["delivered"])),
                    plan["invoiced"],
                    _cents(untaxed),
                    _cents(tax),
                    _cents(untaxed + tax),
                )
            )

        cr.execute(ORDER_TEMP)
        cr.execute(LINE_TEMP)
        cr.execute_values(
            "INSERT INTO _kt_big_order VALUES %s", order_rows, page_size=2000
        )
        cr.execute_values(
            "INSERT INTO _kt_big_line VALUES %s", line_rows, page_size=2000
        )

        columns = set(self._big_columns("sale_order"))
        order_values = {
            "id": "p.order_id",
            "name": "p.name",
            "partner_id": "p.partner_id",
            "partner_invoice_id": "p.partner_id",
            "partner_shipping_id": "p.partner_id",
            "user_id": "p.user_id",
            "date_order": "p.create_date",
            "create_date": "p.create_date",
            "write_date": "p.create_date",
            "validity_date": "p.validity_date",
            "state": "p.state",
            "invoice_status": "p.invoice_status",
            "delivery_status": "p.delivery_status",
            "effective_date": "p.effective_date",
            "commitment_date": "p.commitment_date",
            "amount_untaxed": "p.amount_untaxed",
            "amount_tax": "p.amount_tax",
            "amount_total": "p.amount_total",
            "origin": f"'{BIG_ORIGIN}'",
            "access_token": "NULL",
        }
        self._big_clone(
            "sale_order",
            {c: e for c, e in order_values.items() if c in columns},
            f"_kt_big_order p CROSS JOIN sale_order t WHERE t.id = {ctx['template_order']}",
        )

        columns = set(self._big_columns("sale_order_line"))
        line_values = {
            "id": "l.line_id",
            "order_id": "l.order_id",
            "sequence": "10 + l.line_no",
            "product_uom_qty": "l.qty",
            "price_unit": "l.price_unit",
            "technical_price_unit": "l.price_unit",
            "discount": "0",
            "price_subtotal": "l.subtotal",
            "price_tax": "l.tax",
            "price_total": "l.total",
            "price_reduce_taxexcl": "l.price_unit",
            "price_reduce_taxinc": "l.reduce_inc",
            "qty_delivered": "l.qty * p.delivered",
            "qty_invoiced": "CASE WHEN p.invoiced THEN l.qty ELSE 0 END",
            "qty_to_invoice": (
                "CASE WHEN p.invoiced OR p.state <> 'sale' THEN 0 ELSE l.qty END"
            ),
            "untaxed_amount_invoiced": "CASE WHEN p.invoiced THEN l.subtotal ELSE 0 END",
            "untaxed_amount_to_invoice": (
                "CASE WHEN p.invoiced OR p.state <> 'sale' THEN 0 ELSE l.subtotal END"
            ),
            "state": "p.state",
            "invoice_status": "p.invoice_status",
            "order_partner_id": "p.partner_id",
            "salesman_id": "p.user_id",
            "create_date": "p.create_date",
            "write_date": "p.create_date",
        }
        self._big_clone(
            "sale_order_line",
            {c: e for c, e in line_values.items() if c in columns},
            "_kt_big_line l JOIN _kt_big_order p ON p.order_id = l.order_id "
            "JOIN sale_order_line t ON t.id = l.tpl_line_id",
        )

        # the taxes of the lines (many2many) : those of the template line
        tax_field = self.env["sale.order.line"]._fields["tax_id"]
        relation, column1, column2 = (
            tax_field.relation,
            tax_field.column1,
            tax_field.column2,
        )
        cr.execute(
            f'INSERT INTO "{relation}" ("{column1}", "{column2}") '
            f'SELECT l.line_id, r."{column2}" FROM _kt_big_line l '
            f'JOIN "{relation}" r ON r."{column1}" = l.tpl_line_id'
        )

        # every inserted order must be the sum of its inserted lines
        cr.execute(
            """
            SELECT count(*) FROM sale_order o JOIN (
                SELECT order_id, sum(price_subtotal) s, sum(price_total) t
                FROM sale_order_line WHERE order_id BETWEEN %s AND %s
                GROUP BY order_id) l ON l.order_id = o.id
            WHERE o.id BETWEEN %s AND %s
              AND (abs(o.amount_untaxed - l.s) > 0.005 OR abs(o.amount_total - l.t) > 0.005)
            """,
            (first_order, first_order + size - 1) * 2,
        )
        if cr.fetchone()[0]:
            raise UserError("Inserted orders do not add up to their lines.")
        cr.execute("DROP TABLE _kt_big_line, _kt_big_order")
        return rng.sample(order_ids, min(3, size))

    # ---- verification against the ORM ---------------------------------------
    def _big_check(self, order_ids):
        """Compare inserted orders with what the ORM computes : every line's
        subtotal, tax and total from a virtual line (nothing is written), and
        the order total the ORM shows. Returns the list of differences."""
        self.env.flush_all()
        self.env.invalidate_all()
        line_model = self.env["sale.order.line"]
        differences = []
        for order in self.env["sale.order"].browse(order_ids):
            for line in order.order_line:
                virtual = line_model.new(
                    {
                        "order_id": order.id,
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.product_uom_qty,
                        "price_unit": line.price_unit,
                        "discount": 0.0,
                        "tax_id": [(6, 0, line.tax_id.ids)],
                    }
                )
                for field in ("price_subtotal", "price_tax", "price_total"):
                    if abs(virtual[field] - line[field]) > 0.005:
                        differences.append(
                            (order.name, line.id, field, line[field], virtual[field])
                        )
            shown = (order.tax_totals or {}).get("total_amount_currency")
            if shown is not None and abs(shown - order.amount_total) > 0.005:
                differences.append(
                    (order.name, "order", "amount_total", order.amount_total, shown)
                )
        return differences

    # ---- public API ---------------------------------------------------------
    def generate_big_sale_demo(
        self,
        n_orders=300_000,
        years=4,
        days=None,
        n_customers=2000,
        n_products=113,
        lines_per_order=4,
        seed=None,
        batch_size=10_000,
        commit=False,
    ):
        """Insert `n_orders` sales orders of `lines_per_order` lines (4 by
        default) spread over the last `years` years (or `days` days).

        Can be called again to add sales : the customers, products and order
        names carry on, and `seed` defaults to a value depending on how many
        orders were already generated (so each call gives new data). With
        `commit`, every batch is committed (an interrupted run keeps what was
        done) : use it outside a module installation.
        """
        self.ensure_one()
        started = time.monotonic()
        sellers = list(self._demo_salespeople())
        if not sellers:
            raise UserError("No demo salesperson found (erp_demo_generator).")
        already = self.env["sale.order"].search_count([("origin", "=", BIG_ORIGIN)])
        rng = random.Random(42 + already if seed is None else seed)
        now = fields.Datetime.now()
        date_start = now - timedelta(days=days if days is not None else 365 * years)

        customers = self._big_customers(n_customers)
        products = self._big_products(n_products)
        if not 1 <= lines_per_order < len(products):
            raise UserError(
                "lines_per_order must be lower than the number of products."
            )
        templates, tpl_lines = self._big_templates(products, customers[:1])
        sequence, prefix, padding = self._big_order_sequence()
        ctx = {
            "lines_per_order": lines_per_order,
            "customer_ids": customers.ids,
            "seller_ids": [user.id for user in sellers],
            "weights": [rng.uniform(0.6, 1.6) for _ in sellers],
            "pids": products.ids,
            "prices": [product.list_price for product in products],
            "tpl_lines": [tpl_lines[product.id].id for product in products],
            "rates": [
                self._big_tax_rate(tpl_lines[product.id]) for product in products
            ],
            "template_order": templates[0].id,
            "sequence": sequence,
            "prefix": prefix,
            "padding": padding,
        }

        created, sample = 0, []
        while created < n_orders:
            size = min(batch_size, n_orders - created)
            sample += self._big_batch(rng, now, date_start, size, ctx)
            created += size
            _logger.info(
                "big sales demo : %s/%s orders (%.0f s)",
                created,
                n_orders,
                time.monotonic() - started,
            )
            if commit:
                self.env.cr.commit()

        templates.unlink()
        for table in ("sale_order", "sale_order_line"):
            self.env.cr.execute(f'ANALYZE "{table}"')
        differences = self._big_check(sample[:60])
        if differences:
            raise UserError(f"Inserted orders differ from the ORM : {differences[:5]}")
        if commit:
            self.env.cr.commit()
        _logger.info(
            "big sales demo done : %s orders of %s lines in %.0f s",
            created,
            lines_per_order,
            time.monotonic() - started,
        )
        return created

    def generate_big_sale_demo_install(self):
        """Called by the module installation : the number of orders is the
        system parameter `kpiten_sale_stock_demo_big.initial_orders`."""
        param = self.env["ir.config_parameter"].sudo()
        n_orders = int(
            param.get_param("kpiten_sale_stock_demo_big.initial_orders", 300_000)
        )
        return self.generate_big_sale_demo(n_orders=n_orders)

    def add_big_sales(self, n_orders=100_000, **kwargs):
        """Add sales afterwards (from an Odoo shell), committed by batch."""
        return self.generate_big_sale_demo(n_orders=n_orders, commit=True, **kwargs)
