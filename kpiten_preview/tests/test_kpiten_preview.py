from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKpitenPreview(TransactionCase):
    def setUp(self):
        super().setUp()
        model = self.env.ref("base.model_res_partner")
        self.dataset = self.env["kt.dataset"].create({"model_id": model.id})
        self.env["res.partner"].create([{"name": f"Preview {i}"} for i in range(30)])

    def _line(self, kind, definition):
        return self.env["kt.dataset.line"].create(
            {
                "dataset_id": self.dataset.id,
                "kind": kind,
                "definition": definition,
                "name": "T",
            }
        )

    def _html(self, line, size=50):
        wizard = self.env["kt.dataset.line.preview"].create(
            {"line_id": line.id, "size": size}
        )
        return wizard.preview_html

    def test_a_card(self):
        html = self._html(self._line("card", 'aggregation = "count"\n'))
        self.assertIn("display-6", html)

    def test_a_data_table_with_a_polars_snippet(self):
        line = self._line(
            "data",
            'd_next = d\nd_next = d_next.select([pl.col("name")]).head(3)',
        )
        html = self._html(line)
        self.assertIn("<table", html)
        self.assertIn("name", html.lower())  # the column

    def test_a_graph(self):
        line = self._line(
            "graph",
            'graph_type = "bar"\n[x]\nname = "name"\naggregation = "none"\n'
            '[y]\nname = "id"\naggregation = "count"\n',
        )
        self.assertIn("<iframe", self._html(line))

    def test_a_wrong_definition_shows_the_error(self):
        line = self._line("data", 'd_next = d\nd_next = d_next.select(open("x"))')
        self.assertIn("alert-danger", self._html(line))

    def test_the_button_opens_the_preview(self):
        line = self._line("card", 'aggregation = "count"\n')
        action = line.action_preview()
        self.assertEqual(action["res_model"], "kt.dataset.line.preview")
        self.assertTrue(
            self.env["kt.dataset.line.preview"].browse(action["res_id"]).preview_html
        )
