from odoo import exceptions
from odoo.tools.safe_eval import safe_eval
from odoo.tests.common import TransactionCase, tagged

from ..compat import LIST


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
        self.assertIn(LIST, action.view_mode)

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

    def test_a_card_is_checked_in_a_pivot_of_its_rows_one_action_per_user(self):
        kt = self.env["kt"]
        domain = [("is_company", "=", True)]
        first = kt.get_check_action("res.partner", "Companies", domain, "color", "type")
        action = self.env["ir.actions.act_window"].browse(first)
        self.assertEqual(safe_eval(action.domain), domain)
        self.assertTrue(action.view_mode.startswith("pivot"))
        context = safe_eval(action.context)
        self.assertEqual(context["pivot_measures"], ["color", "__count"])
        self.assertEqual(context["pivot_row_groupby"], ["type"])
        self.assertFalse(context["active_test"])  # the archived ones are counted
        again = kt.get_check_action("res.partner", "All", [], "name")
        self.assertEqual(again, first)  # rewritten : `name` is not a measure
        context = safe_eval(self.env["ir.actions.act_window"].browse(again).context)
        self.assertEqual(context["pivot_measures"], ["__count"])
