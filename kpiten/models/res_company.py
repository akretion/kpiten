from odoo import _, exceptions, models
from odoo.tools.safe_eval import safe_eval

MODULE = __name__[12 : __name__.index(".", 13)]

SP = "'kpiten_setting_services' system parameter "


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_kpiten_services(self):
        """Inherit to set alternative way to get settings"""
        settings = self.env.ref(
            f"{MODULE}.kpiten_setting_services", raise_if_not_found=False
        )
        if not settings:
            raise exceptions.UserError(_("Missing kpiten services parameters"))
        try:
            res = safe_eval(settings.value)
            if not isinstance(res, dict):
                raise exceptions.ValidationError(_(SP + "should be a python dict"))
            if not res.get("internal_url"):
                raise exceptions.ValidationError(
                    _(SP + "should contains 'internal_url' key")
                )
            if not res.get("external_url"):
                raise exceptions.ValidationError(
                    _(SP + "should contains 'external_url' key")
                )
            return res
        except Exception as err:
            raise exceptions.UserError(
                _(
                    f"Kpiten parameters '{settings}' can't be evaluated correctly."
                    + f"\nFull exception :\n{Exception}"
                )
            ) from err
