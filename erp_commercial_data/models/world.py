"""The world of the demo company : a French company selling and buying abroad.

Zones of customers (a team, a price list and its currency, payment terms, a fiscal
position), foreign vendors (their currency, lead time, incoterm), the categories of the
products, the channels of the sales, the rates of the currencies over the years, the
seasons of the business. The step `setup_demo_world` puts it in place ; the sales and
purchases generators draw from it.
"""

import logging
import math
import random
from datetime import date, datetime, timedelta

from odoo import models

from .erp_demo_generator import (
    CUSTOMER_NAMES,
    DEMO_USERS,
    PRODUCTS,
    ROLE_SALES_MANAGER,
    VENDOR_NAMES,
)

_logger = logging.getLogger(__name__)

# units of the currency for one euro, around which the rate moves over the years
RATES = {"USD": 1.08, "GBP": 0.86, "CHF": 0.96}

# zone -> team, price list (its currency), payment terms, fiscal position (template id)
ZONES = {
    "france": {
        "team": "France",
        "pricelist": ("Tarif France", "EUR"),
        "payment_term": "account.account_payment_term_30days",
        "fiscal_position": "fiscal_position_template_domestic",
    },
    "europe": {
        "team": "Europe",
        "pricelist": ("Tarif Europe", "EUR"),
        "payment_term": "account.account_payment_term_45days",
        "fiscal_position": "fiscal_position_template_intraeub2b",
    },
    "uk": {
        "team": "Europe",
        "pricelist": ("UK price list", "GBP"),
        "payment_term": "account.account_payment_term_45days",
        "fiscal_position": "fiscal_position_template_import_export",
    },
    "switzerland": {
        "team": "Europe",
        "pricelist": ("Tarif Suisse", "CHF"),
        "payment_term": "account.account_payment_term_30days",
        "fiscal_position": "fiscal_position_template_import_export",
    },
    "export": {
        "team": "Grand export",
        "pricelist": ("Export price list", "USD"),
        "payment_term": "account.account_payment_term_immediate",
        "fiscal_position": "fiscal_position_template_import_export",
    },
}
# the zone of a country ; the others are "export"
COUNTRY_ZONE = {"FR": "france", "GB": "uk", "CH": "switzerland"}
EUROPE = {"DE", "IT", "ES", "BE", "NL", "PT", "AT", "LU"}
FRENCH_SPEAKING = {"FR", "BE", "CH", "MA", "LU"}

# the salespeople of each team (the sales manager leads France and sees everything)
TEAMS = {
    "France": ["Lara CLEYTE", "Jim NASTIC", "Marie STOURNE"],
    "Europe": ["Karl AHJUMIDE", "Amar DISSOIR"],
    "Grand export": ["Cécile HONXA"],
}
# how much of the business each zone makes (the French customers are many and small)
ZONE_WEIGHTS = {
    "france": 0.55,
    "europe": 0.25,
    "uk": 0.05,
    "switzerland": 0.04,
    "export": 0.11,
}

# (name, country) : the foreign customers ; the French ones are the names of the sales
# generator (CUSTOMER_NAMES...)
FOREIGN_CUSTOMERS = [
    ("Baumarkt Schneider GmbH", "DE"),
    ("Werkstatt Becker KG", "DE"),
    ("Ferramenta Bianchi Srl", "IT"),
    ("Casa Moretti SpA", "IT"),
    ("Bricolaje García SL", "ES"),
    ("Suministros Navarro SA", "ES"),
    ("Brico Dupont SPRL", "BE"),
    ("Bouwmarkt de Vries BV", "NL"),
    ("Van Dijk Interieur BV", "NL"),
    ("Ferragens Lisboa Lda", "PT"),
    ("Home & Garden Supplies Ltd", "GB"),
    ("Thames Hardware Ltd", "GB"),
    ("Quincaillerie du Léman SA", "CH"),
    ("Holzbau Keller AG", "CH"),
    ("Hudson Home Supply Inc.", "US"),
    ("Pacific Tools LLC", "US"),
    ("Maple Hardware Inc.", "CA"),
    ("Atlas Bricolage SARL", "MA"),
    ("Tokyo Interior KK", "JP"),
    ("Gulf Trading LLC", "AE"),
    ("Casa Brasil Ltda", "BR"),
]

# name -> country, currency, incoterm, lead time in days (min, max) ; the vendors of
# erp_demo_generator are French
FOREIGN_VENDORS = {
    "Shenzhen Hardware Co. Ltd": ("CN", "USD", "FOB", (35, 60)),
    "Ningbo Tools Manufacturing": ("CN", "USD", "FOB", (35, 60)),
    "Werkzeug Müller GmbH": ("DE", "EUR", "EXW", (7, 15)),
    "Ferramenta Rossi SpA": ("IT", "EUR", "EXW", (7, 18)),
    "Midwest Supply Inc.": ("US", "USD", "FOB", (20, 35)),
}
FRENCH_VENDOR = ("FR", "EUR", "DAP", (3, 10))

# the category of each product (PRODUCTS), a path under "All"
CATEGORIES = {
    "Redwood plank": "Bricolage / Bois",
    "Stainless bolt set": "Bricolage / Quincaillerie",
    "Ceramic mug XXL": "Maison / Art de la table",
    "Desk lamp arc": "Maison / Éclairage",
    "Copper pipe 2m": "Bricolage / Plomberie",
    "Marble tile set": "Maison / Revêtements",
    "Ergo chair pro": "Maison / Mobilier",
    "Standing desk oak": "Maison / Mobilier",
    "Ph roll 50m": "Bricolage / Plomberie",
    "Nail gun compact": "Bricolage / Outillage",
    "Smart lock hub": "Maison / Domotique",
    "Garden tool kit": "Jardin",
}

# the channels of a sale (utm.medium) and where it comes from (utm.source), by weight
MEDIUMS = [("Vente directe", 0.55), ("Distributeurs", 0.30), ("Site web", 0.15)]
SOURCES = [
    ("Salon professionnel", 0.20),
    ("Recommandation", 0.30),
    ("Site web", 0.20),
    ("Campagne e-mail", 0.15),
    ("Appel entrant", 0.15),
]

# the weight of each month (January first) : a peak before Christmas, August is quiet
SEASON = [0.85, 0.85, 1.0, 1.0, 1.05, 1.0, 0.9, 0.55, 1.1, 1.15, 1.25, 1.2]


def zone_of(country_code: str) -> str:
    if country_code in COUNTRY_ZONE:
        return COUNTRY_ZONE[country_code]
    return "europe" if country_code in EUROPE else "export"


def seasonal_date(rng, date_start, now):
    """A date between `date_start` and `now`, more often in the busy months and in
    the recent years (slowly growing business)."""
    while True:
        moment = date_start + (now - date_start) * (rng.random() ** 0.8)
        if rng.random() < SEASON[moment.month - 1] / max(SEASON):
            return moment


def weighted(rng, pairs):
    names, weights = zip(*pairs)
    return rng.choices(names, weights)[0]


class ErpDemoWorld(models.Model):
    _inherit = "erp.demo.generator"

    def _demo_steps(self):
        steps = super()._demo_steps()
        # after the users (erp demo data), before the orders : they need the world
        return [*steps[:2], ("world", self.setup_demo_world), *steps[2:]]

    # ---- currencies ----------------------------------------------------------
    def _demo_currencies(self, years=3):
        """USD, GBP and CHF active, with a rate for each month of the last `years`
        (a slow wave around RATES, some noise)."""
        rng = random.Random(7)
        company = self.env.company
        rate_model = self.env["res.currency.rate"]
        today = date.today()
        for index, (code, base) in enumerate(RATES.items()):
            currency = (
                self.env["res.currency"]
                .with_context(active_test=False)
                .search([("name", "=", code)], limit=1)
            )
            currency.active = True
            existing = set(
                rate_model.search(
                    [("currency_id", "=", currency.id), ("company_id", "=", company.id)]
                ).mapped("name")
            )
            values = []
            for month in range(12 * years + 1):
                # the first day of the month, `month` months ago
                index_month = today.year * 12 + today.month - 1 - month
                day = date(index_month // 12, index_month % 12 + 1, 1)
                if day in existing:
                    continue
                wave = 0.04 * math.sin(month / 5 + index)
                values.append(
                    {
                        "currency_id": currency.id,
                        "company_id": company.id,
                        "name": day,
                        "rate": round(base * (1 + wave + rng.uniform(-0.01, 0.01)), 6),
                    }
                )
            rate_model.create(values)

    def demo_rate(self, code: str, moment) -> float:
        """Units of the currency `code` for one euro at `moment` (the month's rate)."""
        if code == "EUR":
            return 1.0
        cache = self.env.context.get("demo_rates")
        key = (code, moment.year, moment.month)
        if cache is not None and key in cache:
            return cache[key]
        currency = self.env["res.currency"].search([("name", "=", code)], limit=1)
        rate = self.env["res.currency.rate"].search(
            [
                ("currency_id", "=", currency.id),
                ("company_id", "=", self.env.company.id),
                (
                    "name",
                    "<=",
                    moment.date() if isinstance(moment, datetime) else moment,
                ),
            ],
            order="name desc",
            limit=1,
        )
        value = rate.rate or RATES.get(code, 1.0)
        if cache is not None:
            cache[key] = value
        return value

    # ---- teams, price lists, categories, channels ------------------------------
    def _demo_teams(self):
        """The three sales teams, with their salespeople ; the sales manager leads
        France."""
        users = {u.name: u for u in self.env["res.users"].search([])}
        manager_name = next(n for n, role in DEMO_USERS if role == ROLE_SALES_MANAGER)
        team_model = self.env["crm.team"]
        default = self.env.ref(
            "sales_team.team_sales_department", raise_if_not_found=False
        )
        teams = {}
        for name, members in TEAMS.items():
            team = team_model.search([("name", "=", name)], limit=1)
            if not team and name == "France" and default:
                team = default
                team.name = name
            if not team:
                team = team_model.create({"name": name})
            member_users = [users[m] for m in members if m in users]
            team.write(
                {
                    "member_ids": [(6, 0, [u.id for u in member_users])],
                    "invoiced_target": {"France": 180000, "Europe": 110000}.get(
                        name, 60000
                    ),
                }
            )
            if name == "France" and manager_name in users:
                team.user_id = users[manager_name]
            teams[name] = team
        return teams

    def _demo_pricelists(self):
        """The price list of each zone, in its currency."""
        pricelists = {}
        for zone, spec in ZONES.items():
            name, code = spec["pricelist"]
            pricelist = self.env["product.pricelist"].search(
                [("name", "=", name)], limit=1
            )
            if not pricelist:
                currency = self.env["res.currency"].search(
                    [("name", "=", code)], limit=1
                )
                pricelist = self.env["product.pricelist"].create(
                    {"name": name, "currency_id": currency.id}
                )
            pricelists[zone] = pricelist
        return pricelists

    def _demo_categories(self):
        """The category tree of the products (`CATEGORIES`), each product in its own."""
        category_model = self.env["product.category"]
        root = self.env.ref("product.product_category_all")
        for product_name, path in CATEGORIES.items():
            parent = root
            for part in path.split(" / "):
                category = category_model.search(
                    [("name", "=", part), ("parent_id", "=", parent.id)], limit=1
                )
                parent = category or category_model.create(
                    {"name": part, "parent_id": parent.id}
                )
            product = self.env["product.product"].search(
                [("name", "=", product_name)], limit=1
            )
            if product:
                product.categ_id = parent

    def _demo_channels(self):
        for model, pairs in (("utm.medium", MEDIUMS), ("utm.source", SOURCES)):
            for name, _weight in pairs:
                if not self.env[model].search([("name", "=", name)], limit=1):
                    self.env[model].create({"name": name})

    # ---- customers and vendors ------------------------------------------------
    def _demo_fiscal_position(self, template):
        return self.env.ref(
            f"account.{self.env.company.id}_{template}", raise_if_not_found=False
        )

    def demo_customers(self):
        """The customers : the French ones of the sales generator, and the foreign
        ones ; each with its country, language, price list, payment terms and fiscal
        position. Returns {partner: zone}."""
        from .sales import EXTRA_COMPANY_NAMES, EXTRA_PERSON_NAMES

        french = CUSTOMER_NAMES + EXTRA_COMPANY_NAMES + EXTRA_PERSON_NAMES
        wanted = [(name, "FR") for name in french] + FOREIGN_CUSTOMERS
        partner_model = self.env["res.partner"]
        pricelists = self._demo_pricelists()
        countries = {
            c.code: c
            for c in self.env["res.country"].search(
                [("code", "in", list({code for _n, code in wanted}))]
            )
        }
        customers = {}
        for name, code in wanted:
            zone = zone_of(code)
            spec = ZONES[zone]
            partner = partner_model.search([("name", "=", name)], limit=1)
            vals = {
                "country_id": countries[code].id,
                "lang": "fr_FR" if code in FRENCH_SPEAKING else "en_US",
                "customer_rank": 1,
                "property_product_pricelist": pricelists[zone].id,
                "property_payment_term_id": self.env.ref(spec["payment_term"]).id,
            }
            position = self._demo_fiscal_position(spec["fiscal_position"])
            if position:
                vals["property_account_position_id"] = position.id
            if partner:
                partner.write(vals)
            else:
                partner = partner_model.create(
                    {
                        "name": name,
                        "is_company": name not in EXTRA_PERSON_NAMES,
                        **vals,
                    }
                )
            customers[partner] = zone
        return customers

    def demo_vendors(self):
        """The vendors : the French ones and the foreign ones, each with its country,
        currency, incoterm and lead time. Returns {partner: (currency code, incoterm,
        (min, max) days)}."""
        partner_model = self.env["res.partner"]
        from .purchases import EXTRA_VENDOR_NAMES

        wanted = {name: FRENCH_VENDOR for name in VENDOR_NAMES + EXTRA_VENDOR_NAMES}
        wanted.update(FOREIGN_VENDORS)
        vendors = {}
        for name, (code, currency_code, incoterm, lead) in wanted.items():
            country = self.env["res.country"].search([("code", "=", code)], limit=1)
            currency = self.env["res.currency"].search(
                [("name", "=", currency_code)], limit=1
            )
            vals = {
                "country_id": country.id,
                "supplier_rank": 1,
                "property_purchase_currency_id": currency.id,
            }
            partner = partner_model.search([("name", "=", name)], limit=1)
            if partner:
                partner.write(vals)
            else:
                partner = partner_model.create(
                    {"name": name, "is_company": True, **vals}
                )
            vendors[partner] = (currency_code, incoterm, lead)
        return vendors

    def setup_demo_world(self):
        """Currencies and their rates, the French language, the teams, the price
        lists, the categories of the products, the channels, the customers and the
        vendors of the demo company."""
        self.ensure_one()
        self.env["res.lang"]._activate_lang("fr_FR")
        self._demo_currencies()
        for product in PRODUCTS:
            self._create_product(*product)
        self._demo_categories()
        self._demo_channels()
        self._demo_teams()
        self.demo_customers()
        self.demo_vendors()
        _logger.info("demo world : currencies, teams, customers, vendors in place")
        return True
