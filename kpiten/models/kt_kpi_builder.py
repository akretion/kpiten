"""The tile builder : a form to create or change a card, a graph or a pivot.

Its fields come from the schema of kpiten-spec (`spec.KINDS`) : one field per top key of
each kind (`graph_by`, `pivot_rows`...), its type, its choices and its help (the tooltip)
from the schema ; a key naming a column is chosen among the columns of the table read
(`kt.kpi.builder.column`). The form shows the fields of the kind of the tile.

Only the keys changed in the form are written in the definition (`spec_edit.set_keys`) :
its comments and its sections (`[labels]`, `[plotly.layout]`...) stay as they are.
"""

from lxml import etree

from odoo import _, api, exceptions, fields, models

from ..compat import set_modifier, spec, spec_edit, tomllib
from ..compat import validate_toml as kt_validate_toml
from .kt_dataset import DERIVED_DT_SUFFIX

NUMERIC_TYPES = ("integer", "float", "monetary")


def _spec_keys():
    """`(kind, key)` of every top key of the kinds of kpiten-spec, `version` apart."""
    if spec is None:
        return []
    return [
        (kind, entry)
        for kind in spec.KINDS.values()
        for entry in kind.entries
        if isinstance(entry, spec.Key) and entry.name != "version"
    ]


def _field_name(kind, key) -> str:
    return f"{kind.name}_{key.name}"


def _spec_field(key):
    """The field of the form for a key of the schema."""
    label = key.name.replace("_", " ").capitalize()
    help_text = key.help or ""
    if key.default not in (None, False, ""):
        help_text = f"{help_text} (default : {key.default})".strip()
    common = {"string": label, "help": help_text or None}
    if key.column:
        domain = "[('builder_id', '=', id), ('table', '=', table)]"
        if key.name == "measure":  # a measure is a number
            domain = domain[:-1] + ", ('numeric', '=', True)]"
        return fields.Many2one(
            "kt.kpi.builder.column", domain=domain, ondelete="set null", **common
        )
    if key.table:
        return fields.Selection(selection="_table_selection", **common)
    if key.choices:
        return fields.Selection([(c, c) for c in key.choices], **common)
    if key.type is bool:
        return fields.Boolean(**common)
    if key.type is int:
        return fields.Integer(**common)
    return fields.Char(**common)


class KtKpiBuilderColumn(models.TransientModel):
    """A column a key of the builder may name : a field of a table of the store, a
    relational path (`partner_id.country_id`), a date part (`date_order.year`) or a
    computed column of the definition."""

    _name = "kt.kpi.builder.column"
    _description = "Column of the tile builder"
    _rec_name = "caption"
    _order = "table, caption"

    builder_id = fields.Many2one("kt.kpi.builder", required=True, ondelete="cascade")
    table = fields.Char(required=True)
    name = fields.Char(required=True)
    caption = fields.Char()
    numeric = fields.Boolean()


class KtKpiBuilder(models.TransientModel):
    _name = "kt.kpi.builder"
    _description = "Tile builder"

    kpi_id = fields.Many2one("kt.kpi", string="KPI", ondelete="cascade")
    name = fields.Char(required=True)
    dataset_id = fields.Many2one("kt.dataset", required=True)
    panel_id = fields.Many2one("kt.panel")
    kind = fields.Selection(
        [(name, name.capitalize()) for name in (spec.KINDS if spec else ())],
        required=True,
        default="graph",
    )
    # the table read : the one of `from`, else the one of the dataset
    table = fields.Char(compute="_compute_table")
    before = fields.Text(help="The definition when the builder opened.")
    definition = fields.Text(
        compute="_compute_definition",
        help="The definition written when applied : only the keys changed, "
        "the comments and the sections kept.",
    )
    validation_msg = fields.Text(compute="_compute_definition")
    column_ids = fields.One2many("kt.kpi.builder.column", "builder_id")

    # one field per top key of each kind : graph_by, pivot_rows...
    locals().update({_field_name(k, key): _spec_field(key) for k, key in _spec_keys()})

    @api.model
    def _table_selection(self):
        datasets = self.env["kt.dataset"].search([])
        return sorted({(d.model_id.model, d.model_id.name) for d in datasets})

    def _kind_keys(self, kind=None):
        kind = kind or self.kind
        return [key for k, key in _spec_keys() if k.name == kind]

    @api.depends(lambda self: ["kind", "dataset_id"] + self._from_fields())
    def _compute_table(self):
        for rec in self:
            field = f"{rec.kind}_from"
            chosen = rec[field] if field in rec._fields else False
            rec.table = chosen or rec.dataset_id.model_id.model or False

    @api.model
    def _from_fields(self):
        return [_field_name(k, key) for k, key in _spec_keys() if key.table]

    # -- the definition -------------------------------------------------------
    def _value(self, key):
        """The value of a key in the form, as the definition writes it (None : unset)."""
        value = self[f"{self.kind}_{key.name}"]
        if key.column:
            return value.name or None
        if value is False and key.type is not bool:
            return None
        if value == "" or (value == 0 and key.type is int and key.default is None):
            return None
        return value

    def _changes(self) -> dict:
        """The keys changed from the definition `before` : a new value, or None when
        it comes back to the default (the key is removed)."""
        try:
            data = tomllib.loads(self.before or "")
        except tomllib.TOMLDecodeError:
            data = {}
        changes = {}
        for key in self._kind_keys():
            old = data.get(key.name, key.default)
            new = self._value(key)
            if (new if new is not None else key.default) == old:
                continue
            changes[key.name] = None if new in (None, key.default) else new
        return changes

    @api.depends(lambda self: ["kind", "before"] + self._key_fields())
    def _compute_definition(self):
        for rec in self:
            if spec_edit is None or not rec.kind:
                rec.definition = rec.validation_msg = False
                continue
            rec.definition = spec_edit.set_keys(rec.before or "", rec._changes())
            messages = kt_validate_toml(rec.definition, rec.kind)
            rec.validation_msg = "\n".join(messages) or False

    @api.model
    def _key_fields(self):
        return [_field_name(kind, key) for kind, key in _spec_keys()]

    # -- the columns -----------------------------------------------------------
    def _load_columns(self):
        """The columns of the tables of the store (the models of the datasets), and the
        computed columns of the definition."""
        Kpi = self.env["kt.kpi"]
        IrField = self.env["ir.model.fields"]
        vals = []
        try:
            computed = tomllib.loads(self.before or "").get("computed") or {}
        except tomllib.TOMLDecodeError:
            computed = {}
        for table, _label in self._table_selection():
            described = {f.name: f for f in IrField.search([("model", "=", table)])}
            for name in sorted(Kpi._valid_columns(Kpi, table)):
                root, _dot, part = name.partition(".")
                field = described.get(root)
                caption = field.field_description if field else root
                if part:
                    caption += (
                        f" ({part})" if part in DERIVED_DT_SUFFIX else f" › {part}"
                    )
                vals.append(
                    {
                        "builder_id": self.id,
                        "table": table,
                        "name": name,
                        "caption": f"{caption} · {name}",
                        "numeric": not part
                        and bool(field)
                        and field.ttype in NUMERIC_TYPES,
                    }
                )
            for name in computed:  # whole days : a number
                vals.append(
                    {
                        "builder_id": self.id,
                        "table": table,
                        "name": name,
                        "caption": f"{name} (computed)",
                        "numeric": True,
                    }
                )
        self.env["kt.kpi.builder.column"].create(vals)

    def _column(self, table, name):
        column = self.column_ids.filtered(
            lambda c: c.table == table and c.name == name
        )[:1]
        if not column:  # a name the lists do not have : kept as it is written
            column = column.create(
                {"builder_id": self.id, "table": table, "name": name, "caption": name}
            )
        return column

    def _load_definition(self):
        """The fields of the form from the definition `before`."""
        try:
            data = tomllib.loads(self.before or "")
        except tomllib.TOMLDecodeError as err:
            raise exceptions.UserError(
                _("The definition is not valid TOML : %s") % err
            ) from err
        vals = {}
        table = data.get("from") or self.dataset_id.model_id.model
        for key in self._kind_keys():
            if key.name not in data:
                continue
            value = data[key.name]
            if key.column:
                value = self._column(table, str(value)).id
            elif key.table and value not in dict(self._table_selection()):
                continue  # an unknown table : the validation of the KPI says it
            vals[f"{self.kind}_{key.name}"] = value
        self.write(vals)

    # -- open, apply ----------------------------------------------------------
    @api.model
    def open_builder(self, vals):
        """Create the builder (`vals` : its KPI, or the dataset, kind and panel of a new
        tile) and open it."""
        if spec is None:
            raise exceptions.UserError(
                _("The tile builder needs kpiten-spec (pip install kpiten-spec).")
            )
        builder = self.create(vals)
        builder._load_columns()
        builder._load_definition()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tile builder"),
            "res_model": self._name,
            "res_id": builder.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_apply(self):
        self.ensure_one()
        if self.validation_msg:
            raise exceptions.UserError(self.validation_msg)
        if self.kpi_id:
            self.kpi_id.definition = self.definition
            kpi = self.kpi_id
        else:
            kpi = self.env["kt.kpi"].create(
                {
                    "name": self.name,
                    "dataset_id": self.dataset_id.id,
                    "kind": self.kind,
                    "panel_id": self.panel_id.id,
                    "definition": self.definition or "\n",
                    "user_id": self.env.user.id,
                }
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": "kt.kpi",
            "res_id": kpi.id,
            "view_mode": "form",
            "target": "current",
        }

    # -- the view : the fields of the schema, per kind ----------------------------
    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        place = (
            arch.find(".//div[@name='spec_fields']") if view_type == "form" else None
        )
        if place is None:
            return arch, view
        for kind in spec.KINDS.values() if spec else ():
            # the keys in two columns : two inner groups in an outer one
            outer = etree.SubElement(place, "group", name=f"keys_{kind.name}")
            set_modifier(outer, "invisible", "kind", "!=", kind.name)
            keys = self._kind_keys(kind.name)
            half = (len(keys) + 1) // 2
            for part in (keys[:half], keys[half:]):
                group = etree.SubElement(outer, "group")
                for key in part:
                    node = etree.SubElement(group, "field", name=_field_name(kind, key))
                    if key.column:
                        node.set("options", "{'no_create': True, 'no_open': True}")
                    if key.required:
                        set_modifier(node, "required", "kind", "=", kind.name)
        return arch, view
