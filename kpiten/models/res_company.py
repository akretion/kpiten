from odoo import _, exceptions, models
from odoo.tools.safe_eval import safe_eval

MODULE = __name__[12 : __name__.index(".", 13)]

SP = "'kpiten_setting_services' system parameter "

# applications known by the menu: named links to each dashboard app
KPITEN_APPS = ("shiny", "nicegui")


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_kpiten_services(self, app_name: str = "shiny"):
        """Inherit to set alternative way to get settings

        Settings is either a per-application dict::

            {"shiny": {"application": "Shiny", "external_url": ...},
             "nicegui": {...}}

        or the legacy single-application dict (then `app_name` is ignored).
        """
        settings = self.env.ref(
            f"{MODULE}.kpiten_setting_services", raise_if_not_found=False
        )
        if not settings:
            raise exceptions.UserError(_("Missing kpiten services parameters"))
        try:
            root = safe_eval(settings.value)
            if not isinstance(root, dict):
                raise exceptions.ValidationError(_(SP + "should be a python dict"))
            if app_name in root and all(isinstance(v, dict) for v in root.values()):
                res = root[app_name]
            else:
                res = root  # legacy single app format (marimo / first release)
            if not res.get("internal_url"):
                raise exceptions.ValidationError(
                    _(SP + f"[{app_name}] should contains 'internal_url' key")
                )
            if not res.get("external_url"):
                raise exceptions.ValidationError(
                    _(SP + f"[{app_name}] should contains 'external_url' key")
                )
            return res
        except Exception as err:
            raise exceptions.UserError(
                _(
                    f"Kpiten parameters '{settings}' can't be evaluated correctly."
                    + f"\nFull exception :\n{err}"
                )
            ) from err
