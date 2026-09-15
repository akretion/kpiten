import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Map an Odoo domain operator to a SQL operator.
_OPS = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    "<": "<",
    ">=": ">=",
    "<=": "<=",
    "in": "IN",
    "not in": "NOT IN",
    "like": "LIKE",
    "not like": "NOT LIKE",
    "ilike": "ILIKE",
    "not ilike": "NOT ILIKE",
    "=like": "LIKE",
    "=ilike": "ILIKE",
}

# Operators matching a pattern (value is a raw pattern, not auto-wrapped).
_PATTERN_OPS = {"like", "ilike", "not like", "not ilike"}
_EQ_PATTERN_OPS = {"=like", "=ilike"}


class KtCardWizard(models.TransientModel):
    """Assist creating a `card` tile saved as a kt.dataset.line record.

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

    def _m2o_fields(self, model: str) -> set[str]:
        """Many2one field names of `model` (they map to `<field>_` columns)."""
        if not model:
            return set()
        return {
            f.name
            for f in self.env["ir.model.fields"].search(
                [("model", "=", model), ("ttype", "=", "many2one")]
            )
        }

    # ---- domain -> sql ------------------------------------------------
    def _domain_to_sql(self, domain: list) -> str:
        """Convert an Odoo domain to a SQL `where` clause.

        Tuples without a logical operator are combined with AND (the Odoo
        default) ; `&`/`|`/`!` are handled by the recursive parser.
        """
        m2o = self._m2o_fields(self._source_model())
        parts = []
        i = 0
        while i < len(domain):
            sql, i = self._parse_domain(domain, i, m2o)
            parts.append(sql)
        return " AND ".join(parts) if len(parts) > 1 else parts[0]

    def _parse_domain(self, domain, i, m2o):
        """Recursively parse a domain list into (sql_clause, next_index)."""
        tok = domain[i]
        if tok == "&":
            left, i = self._parse_domain(domain, i + 1, m2o)
            right, i = self._parse_domain(domain, i, m2o)
            return f"({left} AND {right})", i
        if tok == "|":
            left, i = self._parse_domain(domain, i + 1, m2o)
            right, i = self._parse_domain(domain, i, m2o)
            return f"({left} OR {right})", i
        if tok == "!":
            left, i = self._parse_domain(domain, i + 1, m2o)
            return f"(NOT {left})", i
        # plain leaf : (field, operator, value)
        field, op, value = tok
        return self._leaf_sql(field, op, value, m2o), i + 1

    def _leaf_sql(self, field, op, value, m2o) -> str:
        sqlop = _OPS.get(op)
        if not sqlop:
            raise ValidationError(_("Unsupported domain operator '%s'." % op))
        column = f"{field}_" if field in m2o else field
        if op in ("in", "not in"):
            values = ", ".join(self._sql_value(v) for v in value)
            return f"{column} {sqlop} ({values})"
        if op in _PATTERN_OPS or op in _EQ_PATTERN_OPS:
            pattern = value if isinstance(value, str) else str(value)
            if op in _PATTERN_OPS and "%" not in pattern:
                pattern = f"%{pattern}%"
            return f"{column} {sqlop} {self._sql_value(pattern)}"
        if field in m2o:
            value = self._m2o_id(value)
        return f"{column} {sqlop} {self._sql_value(value)}"

    @staticmethod
    def _m2o_id(value):
        """Extract the id from a many2one domain value."""
        if isinstance(value, dict):
            return value.get("id")
        if isinstance(value, (list, tuple)) and value:
            return value[0]
        return value

    @staticmethod
    def _sql_value(value) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

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
        self.env["kt.dataset.line"].create_tile(
            model,
            definition,
            "card",
            name=name,
            panel_id=self.panel_id.id,
        )
        return {
            "type": "ir.actions.act_window_close",
        }
