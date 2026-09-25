from odoo.tests.common import TransactionCase, tagged

from ..compat import get_param, set_param


@tagged("post_install", "-at_install")
class TestFronts(TransactionCase):
    """The fronts of KpiTen : no menu of their own, a button each on the home page
    (kt.home, the action of the app menu), shown when the address of the front is set.
    """

    def test_the_app_opens_its_home_page_open_to_every_user(self):
        app = self.env.ref("kpiten.kpiten_app")
        self.assertEqual(app.action, self.env.ref("kpiten.kt_home_server_action"))
        self.assertFalse(app.groups_id)
        for front in ("shiny", "nicegui", "marimo"):
            self.assertFalse(
                self.env.ref(f"kpiten.menu_{front}_redirect", raise_if_not_found=False)
            )

    def test_a_user_sees_the_buttons_of_the_fronts_that_are_set(self):
        user = self.env["res.users"].create(
            {
                "name": "Home user",
                "login": "kpiten_home_user",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        key = "kpiten_nicegui_service"
        self.env["ir.config_parameter"].sudo().search([("key", "=", key)]).unlink()
        action = self.env["kt.home"].with_user(user).action_home()
        home = self.env["kt.home"].with_user(user).browse(action["res_id"])
        self.assertTrue(home.shiny_ok and home.marimo_ok)
        self.assertFalse(home.nicegui_ok)
        url = '{"external_url": "http://x:5001", "internal_url": "http://x:5001"}'
        set_param(self.env, key, url)
        (
            home.invalidate_recordset()
            if hasattr(home, "invalidate_recordset")
            else home.invalidate_cache()
        )
        self.assertTrue(home.nicegui_ok)
        self.assertTrue(get_param(self.env, key))

    def test_shiny_and_marimo_are_set_by_the_module(self):
        for front in ("shiny", "marimo"):
            service = self.env.company._get_kpiten_services(front)
            self.assertTrue(service["internal_url"] and service["external_url"])
