from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKtConfig(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env.ref("kpiten.only_one")

    def _graph(self):
        return self.env["kt.config"].get_config_json().get("graph", {})

    def test_the_fill_color_goes_to_the_apps(self):
        self.config.graph_fill_color = "#33d17a"
        self.assertEqual(self._graph()["fill_color"], "#33d17a")

    def test_the_palette_and_the_fill_color_are_apart(self):
        self.config.write({"graph_color_1": "#111111", "graph_fill_color": "#222222"})
        graph = self._graph()
        self.assertEqual(graph["layout"]["colorway"][0], "#111111")
        self.assertEqual(graph["fill_color"], "#222222")

    def test_without_a_fill_color_none_is_sent(self):
        self.config.graph_fill_color = False
        self.assertNotIn("fill_color", self._graph())
