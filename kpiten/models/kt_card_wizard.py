import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from . import kt_sql


class KtCardWizard(models.TransientModel):
    """Assist creating a `card` tile saved as a kt.kpi record.

    The card counts the records matching a condition. Instead of typing raw
    SQL, the user builds an Odoo domain in the form (field / operator / value)
    ; the wizard turns it into the SQL `where` clause of the card definition.
    """

    _name = "kt.card.wizard"
    _description = "Create a KPI card"

    dataset_id = fields.Many2one(
        comodel_name="kt.dataset",
        string="Dataset",
        required=True,
        help="Main model the card counts records from.",
    )
    from_dataset_id = fields.Many2one(
        comodel_name="kt.dataset",
        string="Source table",
        help="Optional : count records from another dataset's table instead of "
        "the dataset model.",
    )
    name = fields.Char(string="Name", help="Label displayed on the card.")
    panel_id = fields.Many2one(
        comodel_name="kt.panel",
        string="Panel",
        help="Panel the card is placed in (optional).",
    )
    domain = fields.Char(
        string="Condition",
        help="Build the filter with the assisted domain editor.",
    )
    domain_model = fields.Char(
        string="Condition model",
        compute="_compute_domain_model",
        help="Technical model used by the domain editor (set from the dataset).",
    )
    where = fields.Char(
        string="SQL condition (advanced)",
        help="Optional raw SQL condition used when no domain is set, e.g. "
        "state = 'done'.",
    )

    @api.depends("dataset_id")
    def _compute_domain_model(self):
        for rec in self:
            rec.domain_model = rec.dataset_id.model_id.model or ""

    @api.onchange("dataset_id", "from_dataset_id")
    def _onchange_dataset(self):
        self.domain = ""
        self.where = False

    def _default_name(self):
        return self.dataset_id.name or self.dataset_id.model_id.name

    def _source_model(self) -> str:
        """Technical model of the table the card counts records on."""
        if self.from_dataset_id:
            return self.from_dataset_id.model_id.model
        return self.dataset_id.model_id.model

    # ---- domain -> sql ------------------------------------------------
    def _domain_to_sql(self, domain: list) -> str:
        """Convert an Odoo domain to a SQL `where` clause.

        Tuples without a logical operator are combined with AND (the Odoo
        default) ; `&`/`|`/`!` are handled by the recursive parser.
        """
        return kt_sql._domain_to_sql(self.env[self._source_model()], domain)

    # ---- build & create ----------------------------------------------
    def _build_definition(self) -> str:
        """Build the TOML definition of the card."""
        data = {}
        where = self._build_where()
        if where:
            data["where"] = where
        if self.from_dataset_id:
            data["from"] = self.from_dataset_id.model_id.model
        if not data.get("where"):
            # card_case needs a valid where : count every row
            data["where"] = "id is not null"
        return "\n".join(f"{k} = {json.dumps(v)}" for k, v in data.items())

    def _build_where(self) -> str:
        """The SQL where clause : from the assisted domain, else the free SQL."""
        if self.domain:
            try:
                domain = json.loads(self.domain)
            except json.JSONDecodeError as err:
                raise ValidationError(_("Invalid domain: %s") % err)
            return self._domain_to_sql(domain)
        return (self.where or "").strip()

    def action_create_card(self):
        """Generate the definition and create the card tile in odoo."""
        self.ensure_one()
        model = self.dataset_id.model_id.model
        if not model:
            raise ValidationError(_("No dataset model selected."))
        definition = self._build_definition()
        name = self.name or self._default_name()
        self.env["kt.kpi"].create_tile(
            model,
            definition,
            "card",
            name=name,
            panel_id=self.panel_id.id,
        )
        return {
            "type": "ir.actions.act_window_close",
        }
