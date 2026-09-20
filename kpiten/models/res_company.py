import json

from odoo import _, exceptions, models

# one system parameter per front, holding one dict, set by the module of that front
# (kpiten_shiny, kpiten_nicegui, kpiten_marimo) : `kpiten_shiny_service`,
# `kpiten_nicegui_service`, `kpiten_marimo_service`
SERVICE_KEY = "kpiten_%s_service"


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_kpiten_services(self, app_name: str = "shiny"):
        """The urls of a front : `{"application", "internal_url", "external_url"}`.

        `internal_url` is where Odoo asks for a session (SSO), `external_url` what the
        browser of the user opens. Inherit to set an alternative way to get them.
        """
        key = SERVICE_KEY % app_name
        # system parameters are readable by the Settings group only, while any
        # dashboard user needs the app urls (they hold no secret)
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        if not value:
            raise exceptions.UserError(
                _(
                    "No service for the '%(app)s' front : install its module or set "
                    "the '%(key)s' system parameter",
                    app=app_name,
                    key=key,
                )
            )
        try:
            service = json.loads(value)
        except ValueError as err:
            raise exceptions.UserError(
                _(
                    "The '%(key)s' system parameter is not json : %(err)s",
                    key=key,
                    err=err,
                )
            ) from err
        if not isinstance(service, dict):
            raise exceptions.UserError(
                _("The '%(key)s' system parameter should be a dict", key=key)
            )
        for url in ("internal_url", "external_url"):
            if not service.get(url):
                raise exceptions.UserError(
                    _(
                        "The '%(key)s' system parameter has no '%(url)s'",
                        key=key,
                        url=url,
                    )
                )
        return service
