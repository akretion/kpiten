import logging

import requests as rq
import json
from werkzeug.wrappers import Response
from werkzeug.utils import redirect
from typing import Any

import odoo.http as http
from odoo import SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.http import Controller, request

ROUTE = "/kpiten/<string:model>"
EXCLUDED_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]

logger = logging.getLogger(__name__)


class kpiten(Controller):

    def get_stored_fields(self, user_id, model_name, m2o=False):
        res = (
            request.env["ir.model.fields"]
            .with_user(user_id)
            .search([("model", "=", model_name)])
            .filtered(lambda s: s.store)
        )
        if m2o:
            res = res.filtered(lambda s: s.ttype == "many2one")
        else:
            res = res.filtered(lambda s: s.ttype not in EXCLUDED_TYPES)
        return res

    @http.route("/kpiten/read_kpiten_config", type="http", auth="user")
    def _read_kpiten_config(self):
        # TO DO : avoid building profiles by reassignment
        # in nested loop (cannot find better solution after reflexion)

        env = request.env
        kpiten_config = env["kpiten.config"]
        kpiten_profiles = []  # { name: string, tables: TableMetadata[] }[]
        profile_name = None
        last_profile_name = kpiten_config.search([])[-1].name
        table_list = []

        for profile in kpiten_config.search([]):
            if profile_name is not None and profile_name is not profile.name:
                # this iteration is about to build another profile, meaning
                # that what is currently in memory is a full profile
                kpiten_profiles.append({"name": profile_name, "tables": table_list})
            profile_name = profile.name
            table_list = []
            for model in profile.model_ids:  # getting all table data of one profile
                fields = self.get_stored_fields(request.env.user.id, model.name)
                fields = [x.name for x in fields.search([])]

                all_fields = self.get_stored_fields(SUPERUSER_ID, model.name)
                all_fields = [x.name for x in all_fields.search([])]

                table_list.append(
                    {
                        "table": model.name,
                        "record_name": model._rec_name,
                        "fields": list(set(fields)),
                        "all_fields": list(set(all_fields)),
                    }
                )

        # for the last profile
        kpiten_profiles.append({"name": profile_name, "tables": table_list})

        return Response(json.dumps(kpiten_profiles), status=200)

    @http.route("/kpiten/cmp/<string:uuid>", type="http", auth="user")
    def _compare_UUID(self, uuid, **kwargs):
        env = request.env
        res = env["res.users.log"].search([("uuid", "=", uuid)])
        user = res.create_uid

        if user:
            return Response(status=200)
        else:
            return Response(status=500)

    @http.route([ROUTE], type="http", auth="user")
    def _get_model_data(self, model):
        if model not in request.env.registry.models.keys():
            raise UserError(_(f"Unknown '{model}' in current Database !"))
        env = request.env

        def get_stored_fields(user_id, model_name, m2o=False):
            res = (
                env["ir.model.fields"]
                .with_user(user_id)
                .search([("model", "=", model_name)])
                .filtered(lambda s: s.store)
            )
            if m2o:
                res = res.filtered(lambda s: s.ttype == "many2one")
            else:
                res = res.filtered(lambda s: s.ttype not in EXCLUDED_TYPES)
            return res

        def get_m2o_meta(fields):
            """
            rec_name + rec_name_search are ~ main fields

            return sample
            { ...,
                'commercial_partner_id': {
                    'model': 'res.partner',
                    'rec_name': ['name'],
                    'rec_name_search': ['complete_name']}
             ..., }
            """

            def stored(names):
                """_rec_name and _rec_name_search may contains non stored fields"""
                if not names:
                    return False
                if isinstance(names, str):
                    # _rec_name case
                    names = [names]
                return [
                    x
                    for x in names
                    if x and x in get_stored_fields(SUPERUSER_ID, field.relation)
                ]

            meta = {}
            for field in fields:
                if env[field.relation]._rec_name:
                    meta[field.name] = {
                        "model": field.relation,
                        "rec_name": stored(env[field.relation]._rec_name),
                        "rec_name_search": stored(
                            env[field.relation]._rec_names_search
                        ),
                    }
            return meta

        # rules = env["ir.rule"]._compute_domain(model, mode="read")
        # where_clauses = env[model].sudo()._where_calc(rules)._where_clauses
        services = env["res.company"]._get_kpiten_services()
        for service in services:
            app = service.get("application")
            url = service.get("url")
            if not url:
                raise UserError(_(f"Missing url for application '{app}'"))
            try:
                logger.info(f"Ask for {url}")
                res = rq.post(
                    url,
                    json={
                        "table": env[model]._table,
                        "m2o_meta": get_m2o_meta(
                            get_stored_fields(SUPERUSER_ID, model, m2o=True)
                        ),
                        "record_name": env[model]._rec_name,
                        "fields": get_stored_fields(env.user.id, model).mapped("name"),
                        "all_fields": get_stored_fields(SUPERUSER_ID, model).mapped(
                            "name"
                        ),
                        # "where_clauses": where_clauses,
                    },
                    timeout=100,
                )
                if res.ok:
                    if service.get("redirect"):
                        return redirect(service["redirect"])
                    return redirect(url)
                else:
                    logger.warning(f"REDIRECT TO {app} FAILED : {res}")
                    logger.warning(f"Error content : {res.content}")
                    if service.get("redirect"):
                        return redirect(service["redirect"])
            except KeyError:
                return redirect("/", code=403)
