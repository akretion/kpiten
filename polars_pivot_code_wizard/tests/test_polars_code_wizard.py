import base64
import io

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

try:
    import polars as pl
except ImportError:
    pl = None


@tagged("post_install", "-at_install")
class TestPolarsPivotCodeWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wizard_model = cls.env["polars.pivot.code.wizard"]
        cls.partner_model = cls.env.ref("base.model_res_partner")

    def _new_wizard(self):
        return self.wizard_model.create({"model_id": self.partner_model.id})

    def _col(self, wizard, name):
        return wizard.column_ids.filtered(lambda c: c.name == name)

    def test_no_columns_before_extract(self):
        """Without extracted sample the wizard has no columns to pick."""
        wizard = self._new_wizard()
        self.assertFalse(wizard.column_ids)
        self.assertFalse(wizard.index_field)

    def test_extract_populates_columns(self):
        """After extraction the wizard exposes the Parquet columns as
        Many2one rows, so the Index/Column dropdowns have options."""
        wizard = self._new_wizard()
        wizard.action_extract_sample()

        self.assertTrue(wizard.sample_file)
        self.assertTrue(wizard.column_ids)
        self.assertTrue(self._col(wizard, "name"))

        # The extracted sample must actually be readable as a Parquet file.
        if pl is not None:
            df = pl.read_parquet(io.BytesIO(base64.b64decode(wizard.sample_file)))
            self.assertIn("name", df.columns)

    def test_generate_code_requires_index_and_column(self):
        """Generating code without Index/Column fields raises a UserError."""
        wizard = self._new_wizard()
        with self.assertRaises(UserError):
            wizard.action_generate_code()

    def test_full_pivot_flow(self):
        """Select index/column and check the generated code runs."""
        wizard = self._new_wizard()
        wizard.action_extract_sample()

        wizard.index_field = self._col(wizard, "id")
        wizard.column_field = self._col(wizard, "name")
        wizard.aggregate_function = "len"
        wizard.action_generate_code()

        self.assertTrue(wizard.generated_code)
        self.assertIn("pivot", wizard.generated_code)
        self.assertIn("index='id'", wizard.generated_code)
        self.assertIn("on='name'", wizard.generated_code)
        self.assertTrue(wizard.pivot_html)
        self.assertIn("<table", wizard.pivot_html)
        self.assertTrue(wizard.pivot_preview)

    def test_date_axis_detected_from_column_type(self):
        """Selecting a date column pre-fills the date axis onchange."""
        wizard = self._new_wizard()
        wizard.action_extract_sample()

        wizard.column_field = self._col(wizard, "create_date")
        wizard._onchange_detect_date_axis()
        self.assertTrue(wizard.has_date)
        self.assertEqual(wizard.date_axis, "column")
