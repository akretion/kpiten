from odoo import fields, models
from odoo import SUPERUSER_ID, _
from odoo import api
import json
import logging

logger = logging.getLogger(__name__)

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
    model_ids = fields.Many2many(
        comodel_name="ir.model", help="Models used to produce dataframe"
    )
    company_id = fields.Many2one(comodel_name="res.company")

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
        return res

    @api.model
    def read_kpiten_config(self):
        # TO DO : avoid building profiles by reassignment
        # in nested loop (cannot find better solution after reflexion)
        env = self.env
        kpiten_config = env["kpiten.config"]
        kpiten_profiles = []
        profile_name = None
        profile_id = None
        table_list = []

        for profile in kpiten_config.search([]):
            if profile_name is not None and profile_id is not profile.id:
                # this iteration is about to build another profile, meaning
                # that what is currently in memory is a full profile
                kpiten_profiles.append(
                    {
                        "name": profile_name,
                        "profile_id": profile_id,
                        "tables": table_list,
                    }
                )
            profile_name = profile.name
            profile_id = profile.id
            table_list = []
            for model in profile.model_ids:
                model_fields = [
                    x.name
                    for x in self.get_stored_fields(self.env.user.id, model.model)
                ]
                all_fields = [
                    x.name for x in self.get_stored_fields(SUPERUSER_ID, model.model)
                ]

                table_list.append(
                    {
                        "table": model.name,
                        "technical_name": self.env[model.model]._table,
                        "record_name": model._rec_name,
                        "fields": model_fields,
                        "all_fields": all_fields,
                    }
                )

        # for the last profile
        kpiten_profiles.append(
            {"name": profile_name, "tables": table_list, "profile_id": profile_id}
        )
        logger.info(kpiten_profiles)
        return json.dumps(kpiten_profiles)


class KpitenConfigLine(models.Model):
    _name = "kpiten.config.line"
    _description = "Configuration lines for kpiten"

    config_id = fields.Many2one(comodel_name="kpiten.config", required=True)
    definition = fields.Text(help="Store settings for kpi")
    active = fields.Boolean(default=True)
