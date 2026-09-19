import json

from odoo import exceptions
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKpitenServices(TransactionCase):
    def _set(self, app, value):
        self.env["ir.config_parameter"].sudo().set_param(f"kpiten_{app}_service", value)

    def _get(self, app):
        return self.env.company._get_kpiten_services(app)

    def test_each_front_reads_its_own_parameter(self):
        for app, url in (("front_a", "http://a:1"), ("front_b", "http://b:2")):
            self._set(app, json.dumps({"internal_url": url, "external_url": url}))
        self.assertEqual(self._get("front_a")["internal_url"], "http://a:1")
        self.assertEqual(self._get("front_b")["external_url"], "http://b:2")

    def test_the_urls_can_differ_inside_and_outside(self):
        urls = {"internal_url": "http://app:5000", "external_url": "https://kpi.co"}
        self._set("front_a", json.dumps(urls))
        self.assertEqual(self._get("front_a"), urls)

    def test_a_front_without_parameter_says_what_to_do(self):
        with self.assertRaisesRegex(exceptions.UserError, "kpiten_nothing_service"):
            self._get("nothing")

    def test_a_url_is_required(self):
        self._set("front_a", json.dumps({"internal_url": "http://a:1"}))
        with self.assertRaisesRegex(exceptions.UserError, "external_url"):
            self._get("front_a")

    def test_the_parameter_must_be_a_json_dict(self):
        self._set("front_a", "not json")
        with self.assertRaises(exceptions.UserError):
            self._get("front_a")
        self._set("front_a", json.dumps(["http://a:1"]))
        with self.assertRaisesRegex(exceptions.UserError, "dict"):
            self._get("front_a")
