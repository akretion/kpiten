import logging

import requests as rq
from werkzeug.utils import redirect

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
    @http.route([ROUTE], type="http", auth="user")
    def _get_model_data(self, model):
        if model not in request.env.registry.models.keys():
            raise UserError(_(f"Unknown '{model}' in current Database !"))
        env = request.env

        def get_stored_fields(user_id):
            return (
                env["ir.model.fields"]
                .with_user(user_id)
                .search([("model", "=", model)])
                .filtered(lambda s: s.store and s.ttype not in EXCLUDED_TYPES)
                .mapped("name")
            )

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
                        "record_name": env[model]._rec_name,
                        "fields": get_stored_fields(env.user.id),
                        "all_fields": get_stored_fields(SUPERUSER_ID),
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
