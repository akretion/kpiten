from odoo import exceptions
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKtConfig(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env.ref("kpiten.only_one")

    def _json(self):
        return self.env["kt.config"].get_config_json()

    def _graph(self):
        return self._json().get("graph", {})

    # ---- graphs
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

    def test_the_palette_has_eight_colors(self):
        self.config.write({f"graph_color_{i}": f"#00000{i}" for i in range(1, 9)})
        colorway = self._graph()["layout"]["colorway"]
        self.assertEqual(len(colorway), 8)
        self.assertEqual(colorway[7], "#000008")

    def test_a_gap_in_the_palette_is_skipped(self):
        self.config.write({f"graph_color_{i}": False for i in range(1, 9)})
        self.config.write({"graph_color_1": "#111111", "graph_color_6": "#666666"})
        self.assertEqual(self._graph()["layout"]["colorway"], ["#111111", "#666666"])

    # ---- cards
    def test_the_card_colors_are_sent_only_when_set(self):
        self.config.write({"card_good_color": False, "card_bad_color": False})
        card = self._json()["card"]
        self.assertNotIn("good_color", card)
        self.assertNotIn("bad_color", card)
        self.config.write({"card_good_color": "#123456", "card_bad_color": "#654321"})
        card = self._json()["card"]
        self.assertEqual(
            (card["good_color"], card["bad_color"]), ("#123456", "#654321")
        )

    def test_the_card_preview_shows_the_colors_and_the_fall_that_is_good(self):
        self.config.write({"card_good_color": "#123456", "card_bad_color": "#654321"})
        preview = self.config.card_color_preview
        self.assertIn("#123456", preview)
        self.assertIn("#654321", preview)
        self.assertIn("good = down", preview)  # a fall drawn in the good color
        self.config.write({"card_good_color": False, "card_bad_color": False})
        self.assertIn("#00A04A", self.config.card_color_preview)  # Odoo's green
        self.assertIn("#DC6965", self.config.card_color_preview)

    # ---- numbers
    def test_the_number_settings_are_sent(self):
        self.config.write(
            {
                "number_format": "comma_dot",
                "number_small_below": 100,
                "number_small_decimals": 1,
                "number_large_decimals": 2,
            }
        )
        self.assertEqual(
            self._json()["number"],
            {
                "format": "comma_dot",
                "small_below": 100,
                "small_decimals": 1,
                "large_decimals": 2,
            },
        )

    def test_without_a_number_format_the_server_default_is_kept(self):
        self.config.number_format = False
        self.assertNotIn("format", self._json()["number"])

    def test_the_number_preview_follows_the_settings(self):
        self.config.write(
            {
                "number_format": "comma_dot",
                "number_small_below": 10,
                "number_small_decimals": 2,
                "number_large_decimals": 0,
            }
        )
        preview = self.config.number_preview
        self.assertIn("4,542,884,798</td></tr>", preview)  # large : whole
        self.assertIn("6.76</td></tr>", preview)  # small : two decimals

    def test_decimals_are_bounded(self):
        with self.assertRaises(exceptions.ValidationError):
            self.config.number_small_decimals = 7
        with self.assertRaises(exceptions.ValidationError):
            self.config.number_large_decimals = -1

    # ---- periods
    def test_the_default_period_and_the_fiscal_year(self):
        self.config.write(
            {"default_period": "year to date", "fiscal_year_start_month": "4"}
        )
        self.assertEqual(
            self._json()["period"], {"default": "year to date", "fiscal_start_month": 4}
        )

    def test_the_full_range_is_an_empty_period(self):
        self.config.default_period = "full range"
        self.assertEqual(self._json()["period"]["default"], "")

    # ---- interface, explore, AI
    def test_the_interface_settings_are_sent(self):
        self.config.write({"default_theme": "midnight", "table_rows": 35})
        self.assertEqual(self._json()["ui"], {"theme": "midnight", "table_rows": 35})
        with self.assertRaises(exceptions.ValidationError):
            self.config.table_rows = 0

    def test_the_export_settings_are_sent(self):
        self.config.write({"explore_access": "managers", "explore_max_rows": 1000})
        self.assertEqual(
            self._json()["explore"], {"access": "managers", "max_rows": 1000}
        )
        with self.assertRaises(exceptions.ValidationError):
            self.config.explore_max_rows = 0

    def test_the_ai_switches_are_sent(self):
        self.config.write({"ai_enabled": False, "ai_send_values": False})
        self.assertEqual(self._json()["ai"], {"enabled": False, "send_values": False})

    def test_the_defaults_change_nothing_for_the_apps(self):
        """A record with its default values asks for what the apps already do."""
        fresh = self.env["kt.config"].new({})
        self.assertEqual(fresh.default_period, "last 90 days")
        self.assertEqual(fresh.fiscal_year_start_month, "1")
        self.assertEqual(fresh.default_theme, "akretion")
        self.assertEqual(fresh.table_rows, 20)
        self.assertEqual(fresh.explore_access, "everyone")
        self.assertTrue(fresh.ai_enabled and fresh.ai_send_values)
        self.assertEqual(
            (
                fresh.number_small_below,
                fresh.number_small_decimals,
                fresh.number_large_decimals,
            ),
            (10, 2, 0),
        )

    # ---- new features
    def test_the_new_features_are_off_by_default(self):
        fresh = self.env["kt.config"].new({})
        for name in (
            "save_tile",
            "alerts",
            "concentration",
            "outliers",
            "export_ods",
            "ai_refine",
            "open_in_odoo",
        ):
            self.assertFalse(fresh[f"feature_{name}"], name)

    def test_the_features_are_sent_to_the_apps(self):
        self.config.write({"feature_alerts": True, "feature_outliers": False})
        features = self._json()["features"]
        self.assertTrue(features["alerts"])
        self.assertFalse(features["outliers"])
        self.assertEqual(
            set(features),
            {
                "save_tile",
                "alerts",
                "concentration",
                "outliers",
                "export_ods",
                "ai_refine",
                "open_in_odoo",
            },
        )

    def test_the_data_file_gives_the_eight_colors_of_the_palette(self):
        """A new database opens with a palette of 8 : the record of `data/misc.xml`."""
        import re

        from odoo.tools import file_open

        with file_open("kpiten/data/misc.xml") as handle:
            xml = handle.read()
        colors = {
            int(number): color
            for number, color in re.findall(
                r'name="graph_color_(\d)">(#[0-9a-fA-F]{6})<', xml
            )
        }
        self.assertEqual(sorted(colors), list(range(1, 9)))
        self.assertEqual(len(set(colors.values())), 8)  # eight different colors
