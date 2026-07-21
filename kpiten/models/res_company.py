from odoo import _, exceptions, models
from odoo.tools.safe_eval import safe_eval


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_kpiten_services(self):
        """Inherit to set alternative way to get settings"""
        settings = self.env.ref(
            "kpiten.kpiten_setting_services", raise_if_not_found=False
        )
        if not settings:
            raise exceptions.UserError(_("Missing kpiten services parameters"))
        try:
            print(settings.value)
            res = safe_eval(settings.value)
            if not isinstance(res, list):
                raise exceptions.ValidationError(
                    _(
                        "'kpiten_setting_services' system parameter "
                        "should be a python list"
                    )
                )
            return res
        except Exception as err:
            raise exceptions.UserError(
                _(
                    f"Kpiten parameters '{settings}' can't be evaluated correctly."
                    + f"\nFull exception :\n{Exception}"
                )
            ) from err
