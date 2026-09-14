import json

from kpiten_core.backends.json2 import Json2Backend
from kpiten_core.backend import Backend
import pytest


def test_backend_factory():
    assert Backend.create.__qualname__ == "Backend.create"


def test_json2_stub_is_not_implemented():
    with pytest.raises(NotImplementedError) as err:
        Json2Backend()
    assert "JSON-2" in str(err.value)
