import logging

from odoo import _, api, exceptions, fields, models

from odoo.addons.erp_commercial_data.models.sales import SALE_RATES
from odoo.addons.erp_commercial_data_big.models.erp_demo_generator import BIG_ORIGIN

_logger = logging.getLogger(__name__)

GENERATOR = "erp_commercial_data_big.demo_generator_sale_big"
CRON = "kpiten_commercial_data_big.ir_cron_generate_demo"


class KtConfig(models.Model):
    _inherit = "kt.config"

    # ---- the volume and the lifecycle of the orders to generate
    demo_orders = fields.Integer(
        string="Sales orders",
        default=600000,
        help="How many sales orders a generation adds.",
    )
    demo_lines_per_order = fields.Integer(
        string="Lines per order",
        default=4,
        help="Each order gets this many lines, of different products.",
    )
    demo_years = fields.Integer(
        string="Years of history",
        default=5,
        help="The orders are spread over the last years, until today : a little more "
        "each year, more in the busy months.",
    )
    demo_confirmed_rate = fields.Float(
        string="Confirmed (%)",
        default=SALE_RATES["confirmed"] * 100,
        digits=(5, 1),
        help="The share of confirmed orders ; the others are quotations (recent, "
        "draft or sent) or cancelled.",
    )
    demo_delivered_rate = fields.Float(
        string="Delivered (% of the confirmed)",
        default=SALE_RATES["delivered"] * 100,
        digits=(5, 1),
        help="The share of the confirmed orders delivered once due (a picking done) ; "
        "the others wait for their delivery, some of them partly delivered with a "
        "backorder. The recent orders are not due yet.",
    )
    demo_invoiced_rate = fields.Float(
        string="Invoiced (% of the delivered)",
        default=SALE_RATES["invoiced"] * 100,
        digits=(5, 1),
        help="The share of the delivered orders that got their customer invoice "
        "(posted, not paid) ; only an order delivered in full is invoiced.",
    )

    # ---- the generation, by the cron
    demo_state = fields.Selection(
        [
            ("idle", "Not started"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        string="Generation",
        default="idle",
        readonly=True,
    )
    demo_done = fields.Integer(
        string="Orders generated", readonly=True, help="By the current generation."
    )
    demo_message = fields.Char(string="Last generation", readonly=True)
    demo_total = fields.Integer(
        string="Demo orders in the database",
        compute="_compute_demo_total",
        help="All the generations added up.",
    )

    @api.constrains(
        "demo_orders",
        "demo_lines_per_order",
        "demo_years",
        "demo_confirmed_rate",
        "demo_delivered_rate",
        "demo_invoiced_rate",
    )
    def _check_demo(self):
        for rec in self:
            if rec.demo_orders < 1 or not 1 <= rec.demo_lines_per_order <= 20:
                raise exceptions.ValidationError(
                    _("At least one order, of 1 to 20 lines.")
                )
            if not 1 <= rec.demo_years <= 20:
                raise exceptions.ValidationError(_("The history lasts 1 to 20 years."))
            for rate in (
                rec.demo_confirmed_rate,
                rec.demo_delivered_rate,
                rec.demo_invoiced_rate,
            ):
                if not 0 <= rate <= 100:
                    raise exceptions.ValidationError(
                        _("A share is between 0 and 100 %.")
                    )

    def _compute_demo_total(self):
        total = (
            self.env["sale.order"].sudo().search_count([("origin", "=", BIG_ORIGIN)])
        )
        for rec in self:
            rec.demo_total = total

    def action_generate_demo(self):
        """Queue a generation : the cron runs it in the background."""
        self.ensure_one()
        if self.search_count([("demo_state", "in", ("queued", "running"))]):
            raise exceptions.UserError(_("A generation is already on its way."))
        self.write({"demo_state": "queued", "demo_done": 0, "demo_message": False})
        self.env.ref(CRON).sudo()._trigger()
        return True

    def _demo_generate(self):
        """Generate what the configuration says, committed by batch : the progress
        and the outcome are written on the configuration."""
        self.ensure_one()
        cr = self.env.cr
        self.write({"demo_state": "running", "demo_done": 0, "demo_message": False})
        cr.commit()

        def progress(done, _total):
            self.write({"demo_done": done})
            cr.commit()

        try:
            created = (
                self.env.ref(GENERATOR)
                .sudo()
                .generate_big_sale_demo(
                    n_orders=self.demo_orders,
                    lines_per_order=self.demo_lines_per_order,
                    years=self.demo_years,
                    confirmed_rate=self.demo_confirmed_rate / 100,
                    delivered_rate=self.demo_delivered_rate / 100,
                    invoiced_rate=self.demo_invoiced_rate / 100,
                    commit=True,
                    progress=progress,
                )
            )
        except Exception as error:
            cr.rollback()
            _logger.exception("the generation of the demo data failed")
            self.write({"demo_state": "failed", "demo_message": str(error)[:250]})
        else:
            self.write(
                {
                    "demo_state": "done",
                    "demo_message": _(
                        "%(count)s orders generated on %(date)s",
                        count=created,
                        date=fields.Date.today(),
                    ),
                }
            )
        cr.commit()

    @api.model
    def _cron_generate_demo(self):
        """The queued generation, if any."""
        config = self.search([("demo_state", "=", "queued")], limit=1)
        if config:
            config._demo_generate()
