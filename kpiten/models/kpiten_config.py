import json
import logging

from odoo import SUPERUSER_ID, api, fields, models

logger = logging.getLogger(__name__)

# TODO remove
EXCLUDED_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]


class KpitenConfig(models.Model):
    _name = "kpiten.config"
    _description = "Configuration for kpiten"

    name = fields.Char(required=True)
    state = fields.Selection(selection=[("draft", "Draft"), ("validated", "Validated")])
    line_ids = fields.One2many(
        comodel_name="kpiten.config.line", inverse_name="config_id"
    )
    model_id = fields.Many2one(
        comodel_name="ir.model", help="Main model to produce dataframe"
    )
    model_ids = fields.Many2many(
        comodel_name="ir.model",
        string="Models",
        help="Other models used to complete dataframe",
    )
    company_id = fields.Many2one(comodel_name="res.company")
    group_ids = fields.Many2many(comodel_name="res.groups")

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
        useless_fields = self.env["kpiten"].get_useless_fields().get(model_name)
        if useless_fields:
            res = res.filtered(lambda s: s.name not in useless_fields)
        return res


class KpitenConfigLine(models.Model):
    _name = "kpiten.config.line"
    _description = "Configuration lines for kpiten"

    config_id = fields.Many2one(comodel_name="kpiten.config", required=True)
    definition = fields.Text(required=True, help="Store settings for kpi")
    group_ids = fields.Many2many(comodel_name="res.groups")
    kind = fields.Selection(
        selection=[
            ("data", "Data"),
            ("graph", "Graph"),
            ("ban", "BAN"),
            ("union", "Union"),
        ],
        default="data",
        help="Representation type",
    )
    active = fields.Boolean(default=True)

    @api.model
    def get_conf_id(self, model):
        model_id = self.env["ir.model"].search([("model", "=", model)])
        if len(model_id) >= 1:
            return (
                self.env["kpiten.config.line"]
                .config_id.search([("model_id", "=", model_id.id)])
                .id
            )

    @api.model
    def create_conf_line(self, model, definition: str, kind: str):
        res = self.env["kpiten.config.line"].create(
            {
                "config_id": self.get_conf_id(model),
                "definition": definition,
                "kind": kind,
            }
        )
        if res:
            return True
        else:
            return False
