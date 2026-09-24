from odoo.tests.common import TransactionCase, tagged

from ..compat import get_param, set_param


@tagged("post_install", "-at_install")
class TestFronts(TransactionCase):
    """The fronts of KpiTen (data/fronts.xml) : a menu each, that opens the front ; the
    menu is shown when the address of its front is set."""

    def test_the_menus_open_the_fronts(self):
        for front in ("shiny", "nicegui", "marimo"):
            menu = self.env.ref(f"kpiten.menu_{front}_redirect")
            action = self.env.ref(f"kpiten.action_redirect_to_{front}")
            self.assertEqual(menu.parent_id, self.env.ref("kpiten.kpiten_app"))
            self.assertEqual(menu.action, action)
            self.assertIn(f'application="{front}"', action.code)

    def test_shiny_and_marimo_are_set_by_the_module(self):
        for front in ("shiny", "marimo"):
            service = self.env.company._get_kpiten_services(front)
            self.assertTrue(service["internal_url"] and service["external_url"])

    def test_a_menu_follows_the_address_of_its_front(self):
        menu = self.env.ref("kpiten.menu_nicegui_redirect")
        key = "kpiten_nicegui_service"
        url = '{"external_url": "http://x:5001", "internal_url": "http://x:5001"}'
        set_param(self.env, key, url)
        self.assertTrue(menu.active)
        self.env["ir.config_parameter"].sudo().search([("key", "=", key)]).unlink()
        self.assertFalse(menu.active)
        self.assertFalse(get_param(self.env, key))
