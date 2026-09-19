from odoo import exceptions
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRecordsAction(TransactionCase):
    def setUp(self):
        super().setUp()
        model = self.env.ref("base.model_res_partner")
        self.env["kt.dataset"].create({"model_id": model.id})

    def test_a_dataset_model_has_a_list_action_on_the_ids_it_is_given(self):
        action = self.env["ir.actions.act_window"].browse(
            self.env["kt"].get_records_action("res.partner")
        )
        self.assertEqual(action.res_model, "res.partner")
        self.assertEqual(action.domain, "[('id', 'in', active_ids)]")
        self.assertIn("list", action.view_mode)

    def test_the_action_is_made_once(self):
        first = self.env["kt"].get_records_action("res.partner")
        self.assertEqual(self.env["kt"].get_records_action("res.partner"), first)
        count = self.env["ir.actions.act_window"].search_count(
            [("res_model", "=", "res.partner"), ("name", "=", "KpiTen records")]
        )
        self.assertEqual(count, 1)

    def test_only_the_models_of_a_dataset_are_served(self):
        with self.assertRaises(exceptions.UserError):
            self.env["kt"].get_records_action("res.country")
