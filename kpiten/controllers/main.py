import logging

import requests as rq
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

import odoo.http as http
from odoo import SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.http import Controller, request

ROUTE = "/kpiten/<string:model>"

logger = logging.getLogger(__name__)


class kpiten(Controller):
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
