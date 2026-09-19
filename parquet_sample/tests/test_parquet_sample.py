import io

import polars as pl

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestParquetSample(TransactionCase):
    def setUp(self):
        super().setUp()
        self.sampler = self.env["parquet.sample"]
        country = self.env.ref("base.fr")
        self.env["res.partner"].create(
            [{"name": f"Sample {i}", "country_id": country.id} for i in range(30)]
        )

    def test_the_sample_has_the_asked_size(self):
        frame = self.sampler.sample_dataframe("res.partner", 10)
        self.assertEqual(frame.height, 10)
        self.assertIn("name", frame.columns)

    def test_wizard_style_many2one(self):
        frame = self.sampler.sample_dataframe("res.partner", 10)
        self.assertIn("country_id", frame.columns)  # the id
        self.assertIn("country_id.name", frame.columns)  # its name

    def test_store_style_many2one_and_dates(self):
        """As the dashboards' store has it : name in `x`, id in `x_`, a date is a day."""
        frame = self.sampler.sample_dataframe("res.partner", 10, style="store")
        self.assertEqual(frame.schema["country_id"], pl.String)
        self.assertEqual(frame.schema["country_id_"], pl.Int64)
        self.assertEqual(frame.schema["create_date"], pl.Date)
        self.assertIn("France", frame["country_id"].to_list())

    def test_relational_paths_are_columns(self):
        frame = self.sampler.sample_dataframe(
            "res.partner", 10, style="store", extra_paths=["country_id.code"]
        )
        self.assertIn("FR", frame["country_id.code"].to_list())

    def test_parquet_file(self):
        filename, content = self.sampler.sample_parquet("res.partner", 5)
        self.assertEqual(filename, "res_partner_sample.parquet")
        self.assertEqual(pl.read_parquet(io.BytesIO(content)).height, 5)

    def test_the_sample_only_holds_what_the_user_may_read(self):
        """The ORM applies the record rules of the user : no rule-free SQL sample."""
        user = self.env["res.users"].create(
            {
                "name": "Sampler",
                "login": "sampler",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        readable = self.env["res.partner"].with_user(user).search_count([])
        frame = self.sampler.with_user(user).sample_dataframe("res.partner", 1000)
        self.assertEqual(frame.height, readable)

    def test_a_domain_restricts_the_sample(self):
        frame = self.sampler.sample_dataframe(
            "res.partner", 1000, domain=[("name", "like", "Sample %")]
        )
        self.assertEqual(frame.height, 30)
        self.assertTrue(all(n.startswith("Sample ") for n in frame["name"].to_list()))
