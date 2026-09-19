from odoo import _, api, exceptions, fields, models

NUM_COLORS = 8
# what a scorecard of Odoo uses (`baselineColorUp`, `baselineColorDown`)
DEFAULT_GOOD, DEFAULT_BAD = "#00A04A", "#DC6965"
# key -> (thousands separator, decimal mark) : the same as kpiten_core.config
NUMBER_FORMATS = {
    "space_comma": (" ", ","),
    "space_dot": (" ", "."),
    "dot_comma": (".", ","),
    "comma_dot": (",", "."),
}
PERIODS = [
    ("last 7 days", "Last 7 days"),
    ("last 30 days", "Last 30 days"),
    ("last 90 days", "Last 90 days"),
    ("last 180 days", "Last 180 days"),
    ("last 365 days", "Last 365 days"),
    ("year to date", "Year to date"),
    ("last year", "Last year"),
    ("full range", "Full range"),
]


def _format(value, decimals, key):
    """A number as the dashboards write it (see `kpiten_core.numfmt`)."""
    thousands, mark = NUMBER_FORMATS.get(key) or NUMBER_FORMATS["space_comma"]
    text = f"{value:,.{decimals}f}"
    return text.translate(str.maketrans({",": thousands, ".": mark}))


class KtConfig(models.Model):
    """
    One record only : the form view configuration page in old way
    Easy to maintain
    """

    _name = "kt.config"
    _description = "KpiTen configuration"
    _rec_name = "title"

    title = fields.Char(default="Configuration")

    # ---- graphs
    graph_title_font_color = fields.Char(
        string="Graph title font color",
        help="Color of the chart title font (hex, e.g. #dbe4ef).",
    )
    graph_color_1 = fields.Char(
        string="Color 1",
        help="First color of the chart palette. Used for the first bar / "
        "series of each graph.",
    )
    graph_color_2 = fields.Char(
        string="Color 2",
        help="Second color of the chart palette. Used for the second bar / "
        "series of each graph.",
    )
    graph_color_3 = fields.Char(
        string="Color 3",
        help="Third color of the chart palette. Used for the third bar / "
        "series of each graph.",
    )
    graph_color_4 = fields.Char(
        string="Color 4",
        help="Fourth color of the chart palette. Used for the fourth bar / "
        "series of each graph.",
    )
    graph_color_5 = fields.Char(string="Color 5", help="Fifth color of the palette.")
    graph_color_6 = fields.Char(string="Color 6", help="Sixth color of the palette.")
    graph_color_7 = fields.Char(string="Color 7", help="Seventh color of the palette.")
    graph_color_8 = fields.Char(string="Color 8", help="Eighth color of the palette.")
    graph_fill_color = fields.Char(
        string="Filled graph color",
        help="Color of the filled graphs (area) : their line, and their fill at half "
        "opacity. The palette above is for the bars ; empty, the default color "
        "of the chart library is used.",
    )
    graph_color_preview = fields.Html(
        compute="_compute_graph_color_preview",
        sanitize=False,
        help="Live preview of the chart palette.",
    )

    # ---- cards
    show_card_comparison = fields.Boolean(
        string="Compare cards with the previous period",
        default=True,
        help="Show, under the value of a card, its change since the previous "
        "period. Only the cards defined with `compare = true` are concerned : "
        "unchecked, none of them shows the comparison.",
    )
    card_good_color = fields.Char(
        string="Good change color",
        help="Color of a change that is good news (a rise of the revenue, a fall of "
        "the late deliveries). Empty : the green of an Odoo scorecard.",
    )
    card_bad_color = fields.Char(
        string="Bad change color",
        help="Color of a change that is bad news. Empty : the red of an Odoo "
        "scorecard.",
    )
    card_color_preview = fields.Html(
        compute="_compute_card_color_preview",
        sanitize=False,
        help="How the change of a card is drawn with these colors.",
    )

    # ---- numbers
    number_format = fields.Selection(
        [
            ("space_comma", "1 234,56"),
            ("space_dot", "1 234.56"),
            ("dot_comma", "1.234,56"),
            ("comma_dot", "1,234.56"),
        ],
        string="Number format",
        help="Thousands and decimal separators of the cards and the tables. Empty : "
        "the server default (`DECIMAL_MARK`, a comma).",
    )
    number_small_below = fields.Float(
        string="Small numbers below",
        default=10,
        help="In a table, a decimal number smaller than this (in absolute value) keeps "
        "its decimals : 0.42 is not shown as 0.",
    )
    number_small_decimals = fields.Integer(
        string="Decimals of a small number",
        default=2,
        help="Decimals of a number below the limit above.",
    )
    number_large_decimals = fields.Integer(
        string="Decimals of a large number",
        default=0,
        help="Decimals of the other decimal numbers of a table : 0 rounds them to "
        "the unit.",
    )
    number_preview = fields.Html(
        compute="_compute_number_preview",
        sanitize=False,
        help="How a decimal column of a table is written with these settings.",
    )

    # ---- periods
    default_period = fields.Selection(
        PERIODS,
        string="Default period",
        default="last 90 days",
        help="The period a dashboard opens on, when the data reaches it (else the "
        "full range).",
    )
    fiscal_year_start_month = fields.Selection(
        [
            (str(number), name)
            for number, name in enumerate(
                [
                    "January",
                    "February",
                    "March",
                    "April",
                    "May",
                    "June",
                    "July",
                    "August",
                    "September",
                    "October",
                    "November",
                    "December",
                ],
                1,
            )
        ],
        string="Fiscal year starts in month",
        default="1",
        help="First month of the fiscal year : `year to date` and `last year` start "
        "there (1 : January, the calendar year).",
    )

    # ---- interface
    default_theme = fields.Selection(
        [("akretion", "Akretion"), ("midnight", "Midnight"), ("light", "Sand")],
        string="Default theme",
        default="akretion",
        help="The theme a user gets until they choose another one.",
    )
    table_rows = fields.Integer(
        string="Rows of a table",
        default=20,
        help="Rows a table tile shows ; a longer one is cut off, its note says how "
        "many rows it holds.",
    )

    # ---- explore
    explore_access = fields.Selection(
        [
            ("everyone", "Everyone"),
            ("managers", "KpiTen managers"),
            ("nobody", "Nobody"),
        ],
        string="Who may export the rows",
        default="everyone",
        help="Explore downloads the rows of a panel (with the rights of the user) to "
        "explore them in a notebook. Who gets the button.",
    )
    explore_max_rows = fields.Integer(
        string="Rows per table of an export",
        default=500000,
        help="An export is cut at this number of rows per table.",
    )

    # ---- AI (marimo explorer)
    ai_enabled = fields.Boolean(
        string="AI in the marimo explorer",
        default=True,
        help="Uncheck to turn the AI of the explorer off for everyone.",
    )
    ai_send_values = fields.Boolean(
        string="Send the few values of a column to the model",
        default=True,
        help="The AI knows the columns of the table. Checked, it also gets the values "
        "of the columns that have few (state, country...) : it writes better code, "
        "but with an online model those values leave the company. Never a row.",
    )

    # ---- constraints
    @api.constrains("number_small_decimals", "number_large_decimals")
    def _check_decimals(self):
        for rec in self:
            for value in (rec.number_small_decimals, rec.number_large_decimals):
                if not 0 <= value <= 6:
                    raise exceptions.ValidationError(
                        _("Decimals must be between 0 and 6.")
                    )

    @api.constrains("table_rows")
    def _check_table_rows(self):
        for rec in self:
            if not 1 <= rec.table_rows <= 500:
                raise exceptions.ValidationError(
                    _("A table shows between 1 and 500 rows.")
                )

    @api.constrains("explore_max_rows")
    def _check_explore_max_rows(self):
        for rec in self:
            if rec.explore_max_rows < 1:
                raise exceptions.ValidationError(_("An export holds at least 1 row."))

    # ---- previews
    def _palette(self):
        self.ensure_one()
        colors = (self[f"graph_color_{i}"] for i in range(1, NUM_COLORS + 1))
        return [color for color in colors if color]

    @api.depends(*[f"graph_color_{i}" for i in range(1, NUM_COLORS + 1)])
    def _compute_graph_color_preview(self):
        for rec in self:
            colors = rec._palette()
            if not colors:
                rec.graph_color_preview = False
                continue
            swatches = "".join(
                f'<div style="display:inline-block;width:48px;height:48px;'
                f"background:{color};border-radius:6px;margin:0 6px 6px 0;"
                f'border:1px solid rgba(0,0,0,0.2);"></div>'
                for color in colors
            )
            rec.graph_color_preview = (
                f'<div style="display:flex;flex-wrap:wrap;align-items:center;">'
                f"{swatches}</div>"
            )

    @api.depends("card_good_color", "card_bad_color")
    def _compute_card_color_preview(self):
        """Three cards, as a dashboard draws them : what the two colors change, and
        the case of a card where a fall is good news (`good = "down"`)."""
        for rec in self:
            good = rec.card_good_color or DEFAULT_GOOD
            bad = rec.card_bad_color or DEFAULT_BAD
            cards = [
                ("Revenue", "$345 054 925", "▲ 12.3%", good, "a rise is good"),
                ("Revenue", "$301 210 004", "▼ 4.1%", bad, "a fall is bad"),
                (
                    "Late deliveries",
                    "12",
                    "▼ 8.0%",
                    good,
                    "a fall is good : the card says `good = down`",
                ),
            ]
            html = "".join(
                '<div style="display:inline-block;vertical-align:top;width:200px;'
                "margin:0 10px 10px 0;padding:8px 12px;border-radius:8px;"
                'background:#0c0f1e;color:#dbe4ef;font-family:sans-serif">'
                f'<div style="font-size:12px;opacity:.7">{name}</div>'
                f'<div style="font-size:26px;font-weight:700">{value}</div>'
                f'<div style="font-size:12px;font-weight:600;color:{color}">'
                f'{change} <span style="font-weight:400;opacity:.65">'
                "since last period</span></div>"
                f'<div style="font-size:11px;opacity:.55;margin-top:4px">{note}</div>'
                "</div>"
                for name, value, change, color, note in cards
            )
            rec.card_color_preview = f"<div>{html}</div>"

    @api.depends(
        "number_format",
        "number_small_below",
        "number_small_decimals",
        "number_large_decimals",
    )
    def _compute_number_preview(self):
        for rec in self:
            rows = []
            for value in (4542884798.35, 3116.4, 42.36, 9.996, 6.756, 0.42):
                small = abs(value) < rec.number_small_below
                decimals = (
                    rec.number_small_decimals if small else rec.number_large_decimals
                )
                shown = _format(value, decimals, rec.number_format)
                rows.append(
                    "<tr>"
                    f'<td style="text-align:right;padding:2px 12px;opacity:.6">'
                    f"{_format(value, 2, 'comma_dot')}</td>"
                    f'<td style="padding:2px 6px">→</td>'
                    f'<td style="text-align:right;padding:2px 12px;font-weight:600">'
                    f"{shown}</td></tr>"
                )
            rec.number_preview = (
                "<table><tr><th>Value</th><th></th><th>In a table</th></tr>"
                + "".join(rows)
                + "</table>"
            )

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]):
            raise models.ValidationError(
                _("Only one KpiTen configuration record is allowed.")
            )
        return super().create(vals_list)

    @api.model
    def get_config_json(self):
        """The settings as the dashboard apps read them (`kpiten_core.config`).

        i.e. {"graph": {"layout": {"colorway": [...]}, "fill_color": "#33d17a"},
              "card": {"comparison": True, "good_color": "#00A04A"},
              "number": {"format": "space_comma", "small_below": 10, ...},
              "period": {"default": "last 90 days", "fiscal_start_month": 1},
              "ui": {"theme": "akretion", "table_rows": 20},
              "explore": {"access": "everyone", "max_rows": 500000},
              "ai": {"enabled": True, "send_values": True},
              "currency": {"symbol": "$", "position": "before"}}

        `currency` is the one of the company : a card with `unit = "currency"`
        shows it, before or after the number as Odoo does.
        """
        currency = self.env.company.currency_id
        config = {
            "currency": {"symbol": currency.symbol, "position": currency.position}
        }
        rec = self.search([], limit=1)
        if not rec:
            return config
        layout = {}
        colorway = rec._palette()
        if colorway:
            layout["colorway"] = colorway
        if rec.graph_title_font_color:
            layout["title"] = {"font": {"color": rec.graph_title_font_color}}
        graph = {}
        if layout:
            graph["layout"] = layout
        if rec.graph_fill_color:
            graph["fill_color"] = rec.graph_fill_color
        if graph:
            config["graph"] = graph
        card = {"comparison": rec.show_card_comparison}
        if rec.card_good_color:
            card["good_color"] = rec.card_good_color
        if rec.card_bad_color:
            card["bad_color"] = rec.card_bad_color
        config["card"] = card
        config["number"] = {
            "small_below": rec.number_small_below,
            "small_decimals": rec.number_small_decimals,
            "large_decimals": rec.number_large_decimals,
        }
        if rec.number_format:
            config["number"]["format"] = rec.number_format
        config["period"] = {
            "default": "" if rec.default_period == "full range" else rec.default_period,
            "fiscal_start_month": int(rec.fiscal_year_start_month or 1),
        }
        config["ui"] = {"theme": rec.default_theme, "table_rows": rec.table_rows}
        config["explore"] = {
            "access": rec.explore_access,
            "max_rows": rec.explore_max_rows,
        }
        config["ai"] = {
            "enabled": rec.ai_enabled,
            "send_values": rec.ai_send_values,
        }
        return config
