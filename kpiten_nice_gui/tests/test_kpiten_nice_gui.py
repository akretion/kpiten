from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKpitenNiceGui(TransactionCase):
    def test_the_service_is_set_by_the_module(self):
        service = self.env.company._get_kpiten_services("nicegui")
        self.assertEqual(service["application"], "NiceGUI")
        self.assertEqual(service["internal_url"], "http://localhost:5001")
        self.assertTrue(service["external_url"])

    def test_the_menu_opens_the_front(self):
        menu = self.env.ref("kpiten_nice_gui.menu_nicegui_redirect")
        action = self.env.ref("kpiten_nice_gui.action_redirect_to_nicegui")
        self.assertEqual(menu.parent_id, self.env.ref("kpiten.kpiten_app"))
        self.assertEqual(menu.action, action)
        self.assertIn('application="nicegui"', action.code)
