import logging
import re
from html import escape

from markupsafe import Markup

from odoo import _, api, exceptions, fields, models

from ..compat import LIST, sql_constraints, tomllib
from ..compat import is_sql as kt_is_sql
from ..compat import validate_display as kt_validate_display
from ..compat import validate_toml as kt_validate_toml

logger = logging.getLogger(__name__)

# the drill-down of a data tile (see kpiten_core.tiles.split_keys) : the hidden columns
# of the table ("__product_id_"), the keys the drill reads (key["product_id_"] in
# polars, :product_id_ in SQL) and the line 1 of a polars snippet (d_next = d)
HIDDEN_RE = re.compile(r"""["']__(\w+)["']""")
POLARS_KEY_RE = re.compile(r"""\bkey\[\s*["'](\w+)["']\s*\]""")
SQL_KEY_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
FIRST_LINE_RE = re.compile(r"^\w+ = \w+\s*$")

# Suffixes of date columns added dynamically by kpiten-core
# (see kpiten_core.tiles.DERIVED_DT_SUFFIX).
DERIVED_DT_SUFFIX = {"year", "quarter", "month", "week", "day"}

# TODO remove
EXCLUDED_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]


class KtDataset(models.Model):
    _name = "kt.dataset"
    _description = "Data source for kpiten"
    _rec_name = "model_id"

    name = fields.Char(compute="_compute_name", readonly=False)
    state = fields.Selection(selection=[("draft", "Draft"), ("validated", "Validated")])
    line_ids = fields.One2many(
        comodel_name="kt.kpi",
        inverse_name="dataset_id",
        context={"active_test": False},
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        required=True,
        ondelete="cascade",
        help="Main model to produce dataframe",
    )
    sequence = fields.Integer()
    company_id = fields.Many2one(comodel_name="res.company")
    group_ids = fields.Many2many(comodel_name="res.groups")
    line_count = fields.Integer(
        compute="_compute_line_count",
        help="Number of tiles of this dataset, the archived ones included.",
    )

    sql_constraints(
        locals(),
        model_unique=(
            "UNIQUE(model_id,company_id)",
            "Model field must unique by company",
        ),
    )

    @api.constrains("model_id", "company_id")
    def _check_model_unique_no_company(self):
        """UNIQUE(model_id, company_id) lets several (model, NULL) rows through
        since NULL != NULL in SQL: check the "no company" case here."""
        for rec in self.filtered(lambda r: not r.company_id):
            if self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("model_id", "=", rec.model_id.id),
                    ("company_id", "=", False),
                ]
            ):
                raise exceptions.ValidationError(
                    _("Model '%s' already has a dataset without company.")
                    % rec.model_id.display_name
                )

    @api.depends("model_id")
    def _compute_name(self):
        for rec in self:
            if rec.model_id:
                rec.name = rec.model_id.name

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_view_lines(self):
        """The tiles (`kt.kpi`) of this dataset, in a list."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tiles of %s") % self.display_name,
            "res_model": "kt.kpi",
            "view_mode": f"{LIST},form",
            "domain": [("dataset_id", "=", self.id)],
            # the archived tiles are listed too, `active` tells them apart
            "context": {"default_dataset_id": self.id, "active_test": False},
        }

    def _sync_auditlog_rule(self):
        """Subscribe an auditlog rule logging deletions on each dataset model."""
        if "auditlog.rule" not in self.env:
            return
        Rule = self.env["auditlog.rule"]
        for rec in self:
            if not rec.model_id:
                continue
            rule = Rule.search([("model_id", "=", rec.model_id.id)], limit=1)
            if not rule:
                rule = Rule.create(
                    {
                        "name": "kpiten deletions",
                        "model_id": rec.model_id.id,
                        "log_create": False,
                        "log_write": False,
                        "log_read": False,
                        "log_unlink": True,
                        "capture_record": False,
                        "log_type": "fast",
                    }
                )
            if rule.state != "subscribed":
                rule.subscribe()

    def _unsubscribe_freed_models(self, model_ids):
        """Drop the audit rule of models no longer used by any dataset."""
        if not model_ids or "auditlog.rule" not in self.env:
            return
        Rule = self.env["auditlog.rule"]
        for model_id in model_ids:
            if self.env["kt.dataset"].search([("model_id", "=", model_id)], limit=1):
                continue
            rule = Rule.search([("model_id", "=", model_id)], limit=1)
            if rule:
                rule.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._sync_auditlog_rule()
        return recs

    def write(self, vals):
        old_models = {rec.model_id.id for rec in self if rec.model_id}
        res = super().write(vals)
        if "model_id" in vals:
            self._sync_auditlog_rule()
            self._unsubscribe_freed_models(old_models)
        return res

    def unlink(self):
        freed = {rec.model_id.id for rec in self if rec.model_id}
        res = super().unlink()
        self._unsubscribe_freed_models(freed)
        return res

    @api.model
    def _auditlog_installed_sync(self):
        """Configure deletion audit rules for all existing dataset models."""
        self.search([])._sync_auditlog_rule()

    def _register_hook(self):
        res = super()._register_hook()
        # Ensure deletion audit rules exist once auditlog is installed.
        if "auditlog.rule" in self.pool and self.env.registry.ready:
            try:
                self._auditlog_installed_sync()
            except Exception:
                pass
        return res

    # TODO remove: replace by get_fields()
    @api.model
    def get_stored_fields(self, user_id, model_name, m2o=False):
        res = (
            self.env["ir.model.fields"]
            .with_user(user_id)
            .search([("model", "=", model_name)])
            .filtered(lambda s: s.store)
        )
        if m2o:
            res = res.filtered(lambda s: s.ttype == "many2one")
        else:
            res = res.filtered(lambda s: s.ttype not in EXCLUDED_TYPES)
        useless_fields = self.env["kt"].get_useless_fields().get(model_name)
        if useless_fields:
            res = res.filtered(lambda s: s.name not in useless_fields)
        return res


class KtKpi(models.Model):
    _name = "kt.kpi"
    _description = "Configuration lines for kpiten"
    _order = "sequence"

    dataset_id = fields.Many2one(comodel_name="kt.dataset", required=True)
    definition = fields.Text(
        required=True,
        help="TOML settings of a card, graph, pivot or union tile ; for a Data "
        "tile, a polars snippet (see the syntax help under the fields). "
        'The tile reads the table of its dataset ; `from = "sale.order.line"` '
        "reads another one (e.g. the lines of the orders).",
    )
    drill_definition = fields.Text(
        help="Data tile only : run when a row of the table is clicked, to show the "
        "rows behind it. It runs on the same rows as the tile (`d` : rights, period "
        "and filters kept) with the hidden columns of the clicked row : a column of "
        'the tile named `__product_id_` is `key["product_id_"]` in polars, '
        '`:product_id_` in SQL. The other tables : `tables["sale.order"]` in '
        'polars, `FROM "sale.order"` in SQL. Same syntax as the definition : SQL, '
        'or polars with sql("...") inside.',
    )
    display = fields.Text(
        help="Data tile only : TOML, the names shown for its columns ([labels]) and how "
        "its table is drawn ([table] : format, totals, heatmap...). A SQL tile may also "
        "say it in comments at its top (-- [table] ...) ; this field wins.",
    )
    model_id = fields.Many2one(comodel_name="ir.model", related="dataset_id.model_id")
    name = fields.Char()
    group_ids = fields.Many2many(comodel_name="res.groups")
    sequence = fields.Integer()
    kind = fields.Selection(
        selection=[
            ("data", "Data"),
            ("graph", "Graph"),
            ("card", "Card"),
            ("union", "Union"),
            ("pivot", "Pivot"),
        ],
        default="data",
        help="Representation type",
    )
    user_id = fields.Many2one(comodel_name="res.users")
    panel_id = fields.Many2one(comodel_name="kt.panel")
    # Grid layout of the panel
    col_span = fields.Integer(
        default=1,
        help="Number of grid columns spanned by the tile",
    )
    tile_height = fields.Integer(
        default=260,
        help="Height of the tile in pixels",
    )
    table_view = fields.Selection(
        [("table", "Table"), ("grid", "Interactive grid")],
        string="Table view",
        default="table",
        required=True,
        help="How a table tile (data, pivot, union) is drawn in the dashboard. Table : "
        "the numbers formatted, the links to Odoo, the drill-down on a click. "
        "Interactive grid : the user sorts and filters each column.",
    )
    active = fields.Boolean(default=True)
    validation_msg = fields.Text(
        compute="_compute_validation_msg",
        store=True,
        help="Structural validation messages for the definition (non blocking).",
    )
    xml_id = fields.Char(
        string="External ID",
        compute="_compute_xml_id",
        help="The xml id of the tile, when a module's data defines it.",
    )

    def _compute_xml_id(self):
        xml_ids = self.get_external_id()
        for rec in self:
            rec.xml_id = xml_ids.get(rec.id) or False

    @api.model
    def get_conf_id(self, model):
        model_id = self.env["ir.model"].search([("model", "=", model)])
        if len(model_id) >= 1:
            return self.env["kt.dataset"].search([("model_id", "=", model_id.id)]).id

    @api.model
    def create_tile(
        self,
        model: str,
        definition: str,
        kind: str,
        name: str = None,
        user_id: int = None,
        panel_id: int = None,
    ) -> bool:
        """Create a new tile line for the dataset of `model`."""
        self._check_definition(definition, kind)
        res = self.create(
            {
                "dataset_id": self.get_conf_id(model),
                "definition": definition,
                "name": name,
                "kind": kind,
                "user_id": user_id or self.env.user.id,
                "panel_id": panel_id,
            }
        )
        return bool(res)

    def _check_definition(self, definition: str, kind: str) -> None:
        """The definition must be valid TOML (polars code for kind=data)."""
        if kind == "data":
            return  # definition is polars code, not TOML
        try:
            tomllib.loads(definition)
        except tomllib.TOMLDecodeError as err:
            raise exceptions.ValidationError(
                _("Tile definition must be valid TOML :\n%s") % err
            )

    preview_html = fields.Html(
        string="Preview",
        compute="_compute_preview_html",
        sanitize=False,
        help="The KPI as the Shiny dashboard draws it : with the rights of the user, "
        "on the synced data, over the default period. Reloaded when the KPI is saved, "
        "or by the Preview button.",
    )

    def _compute_preview_html(self):
        """An iframe of the tile drawn by Shiny (`/dashboard/tile/<id>`), in a session
        of the current user."""
        saved = self.filtered("id")
        (self - saved).preview_html = Markup('<p class="text-muted">%s</p>') % _(
            "Save the KPI to see its preview."
        )
        if not saved:
            return
        try:
            session, url = self.env["kt"]._kpiten_session("shiny")
        except exceptions.UserError as err:
            saved.preview_html = Markup('<p class="text-muted">%s</p>') % str(err)
            return
        for rec in saved:
            # the date of the last save : a new url, the iframe reloads
            version = int(rec.write_date.timestamp()) if rec.write_date else 0
            src = f"{url}/dashboard/tile/{rec.id}?session={session}&v={version}"
            height = (rec.tile_height or 320) + 40
            rec.preview_html = Markup(
                f'<iframe src="{escape(src)}" loading="lazy" '
                f'style="width: 100%; height: {height}px; border: 0"></iframe>'
            )

    def action_preview(self):
        """Save and reload the preview (the form saves the KPI before a button)."""
        return True

    def action_open_builder(self):
        """The tile builder on this KPI (a card, a graph or a pivot)."""
        self.ensure_one()
        return self.env["kt.kpi.builder"].open_builder(
            {
                "kpi_id": self.id,
                "name": self.name,
                "dataset_id": self.dataset_id.id,
                "panel_id": self.panel_id.id,
                "kind": self.kind,
                "before": self.definition,
            }
        )

    @api.depends("definition", "display", "drill_definition", "kind", "dataset_id")
    def _compute_validation_msg(self):
        for rec in self:
            messages = self._structural_messages(rec) + self._drill_messages(rec)
            rec.validation_msg = "\n".join(messages) if messages else False

    @api.model
    def _drill_messages(self, rec) -> list:
        """What would make the drill-down of a data tile inert or fail : no hidden
        column in the table (nothing to click), a key the table does not give, a
        polars snippet whose line 1 is not `out = in`."""
        if rec.kind != "data" or not rec.drill_definition or kt_is_sql is None:
            return []
        drill = rec.drill_definition
        hidden = set(HIDDEN_RE.findall(rec.definition or ""))
        if not hidden:
            return [
                _(
                    "Drill-down : the table has no hidden column (a name starting "
                    'with __, e.g. AS "__product_id_") : no row can be clicked.'
                )
            ]
        messages = []
        if kt_is_sql(drill):
            used = set(SQL_KEY_RE.findall(drill)) - {"odoo_url"}
        else:
            used = set(POLARS_KEY_RE.findall(drill))
            if not FIRST_LINE_RE.match(drill.partition("\n")[0]):
                messages.append(
                    _("Drill-down : line 1 must be `out = in` (d_next = d).")
                )
        for name in sorted(used - hidden):
            messages.append(
                _(
                    "Drill-down : the key '%(name)s' is not a hidden column of the "
                    "table (__%(name)s) ; there are : %(hidden)s."
                )
                % {"name": name, "hidden": ", ".join(sorted(hidden))}
            )
        return messages

    @api.model
    def _structural_messages(self, rec) -> list:
        """Run the kpiten-core structural validation on a line definition (a data
        tile : its display)."""
        if rec.kind == "data":
            if kt_validate_display is None or not rec.definition:
                return []
            return kt_validate_display(rec.definition, rec.display)
        if kt_validate_toml is None or not rec.definition:
            return []
        try:
            table = tomllib.loads(rec.definition).get("from")
        except tomllib.TOMLDecodeError:
            return [_("Definition is not valid TOML.")]
        model = rec.dataset_id.model_id.model
        messages = []
        if table == model:
            messages.append(
                _("'from' is the model of the dataset : remove it (not needed).")
            )
        elif isinstance(table, str) and table not in self.env:
            messages.append(_("'from' : unknown model '%s'.") % table)
        elif isinstance(table, str):  # the columns are the ones of the table read
            model = table
        fields = self._valid_columns(rec, model)
        return messages + kt_validate_toml(rec.definition, rec.kind, fields)

    def _valid_columns(self, rec, model=None) -> set:
        """Set of valid column names for `model` (by default the dataset one).

        Stored fields + dotted relational paths (as produced by the
        extraction) plus the derived date columns (`<date>.year`, ...).
        """
        model = model or rec.dataset_id.model_id.model
        if not model:
            return set()
        columns = self.env["kt"].get_allowed_fields(model, self.env.user.id)
        columns = set(columns)
        for col in list(columns):
            if self._is_date_column(model, col):
                for suffix in DERIVED_DT_SUFFIX:
                    columns.add(f"{col}.{suffix}")
        return columns

    def _is_date_column(self, model: str, name: str) -> bool:
        """True if `name` is a stored date/datetime column of `model`."""
        field = self.env["ir.model.fields"].search(
            [
                ("model", "=", model),
                ("name", "=", name),
                ("ttype", "in", ("date", "datetime")),
            ],
            limit=1,
        )
        return bool(field)

    def _check_display(self, display: str) -> None:
        """The display of a data tile must be valid TOML."""
        try:
            tomllib.loads(display)
        except tomllib.TOMLDecodeError as err:
            raise exceptions.ValidationError(
                _("Display must be valid TOML :\n%s") % err
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("definition") and vals.get("kind", "data") != "data":
                self._check_definition(vals["definition"], vals["kind"])
            if vals.get("display"):
                self._check_display(vals["display"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("display"):
            self._check_display(vals["display"])
        if vals.get("definition"):
            for line in self:
                kind = vals.get("kind") or line.kind
                if kind != "data":
                    self._check_definition(vals["definition"], kind)
        return super().write(vals)
