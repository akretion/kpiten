import json

from kpiten_core.backends.json2 import Json2Backend
from kpiten_core.backend import Backend
import pytest


def test_backend_factory():
    assert Backend.create.__qualname__ == "Backend.create"


def test_json2_sends_named_arguments_with_the_api_key(monkeypatch):
    """`POST /json/2/<model>/<method>`, the ids and the parameters by name ; the key
    and the database in the headers ; an error of Odoo says its message."""
    monkeypatch.setenv("ODOO_API_KEY", "secret")
    calls = []

    class Answer:
        def __init__(self, status, body):
            self.status_code, self.body = status, body

        def json(self):
            return self.body

    def post(self, url, json=None, timeout=None):
        calls.append((url, json, dict(self.headers)))
        if url.endswith("/kt/check_uuid"):
            return Answer(422, {"message": "bad uuid"})
        return Answer(200, 1)

    monkeypatch.setattr("requests.Session.post", post)
    backend = Json2Backend(db="claude20")
    backend.delete_tile(7)
    url, body, headers = calls[-1]
    assert url.endswith("/json/2/kt.dataset.line/unlink") and body == {"ids": [7]}
    assert headers["Authorization"] == "bearer secret"
    assert headers["X-Odoo-Database"] == "claude20"
    assert backend.check_uuid("x") is None  # the error is logged, not raised
