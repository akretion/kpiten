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

    # TODO remove
    @api.model
    def read_config(self):
        # TO DO : avoid building profiles by reassignment
        # in nested loop (cannot find better solution after reflexion)
        kpiten_profiles = []

        profile_name = None
        profile_id = None
        main_model = None
        main_model_fields = []
        model_list = []  # optional, can turn out empty

        for profile in self.search([]):
            profile_name = profile.name
            profile_id = profile.id
            main_model = profile.model_id
            model_list = []
            main_model_fields = self.get_stored_fields(
                self.env.user.id, profile.model_id.model
            )
            main_model_fields = [x.name for x in main_model_fields]

            # Parsing optional model list
            for model in profile.model_ids:
                model_fields = [
                    x.name
                    for x in self.get_stored_fields(self.env.user.id, model.model)
                ]
                all_fields = [
                    x.name for x in self.get_stored_fields(SUPERUSER_ID, model.model)
                ]

                model_list.append(
                    {
                        "name": model.name,
                        "table": self.env[model.model]._table,
                        "record_name": model._rec_name,
                        "fields": model_fields,
                        "all_fields": all_fields,
                    }
                )

            kpiten_profiles.append(
                {
                    "name": profile_name,
                    "main_model": self.env[main_model.model]._table,
                    "main_record_name": main_model._rec_name,
                    "main_model_fields": main_model_fields,
                    "models": model_list,
                    "profile_id": profile_id,
                }
            )

        print(f"""
        LEN OF KPITEN PROFILES : {len(kpiten_profiles)},\n
        KPITEN_PROFILES : \n
        -----------
        {kpiten_profiles}\n
        -----------
        """)
        return json.dumps(kpiten_profiles)


class KpitenConfigLine(models.Model):
    _name = "kpiten.config.line"
    _description = "Configuration lines for kpiten"

    config_id = fields.Many2one(comodel_name="kpiten.config", required=True)
    definition = fields.Text(required=True, help="Store settings for kpi")
    group_ids = fields.Many2many(comodel_name="res.groups")
    kind = fields.Selection(
        selection=[("data", "Data"), ("graph", "Graph")],
        default="data",
        help="Representation type",
    )
    active = fields.Boolean(default=True)
