from typing import Any

from kpiten_core.backends import jsonrpc


class Json2Backend:
    """Odoo >= 19 External JSON-2 API backend (stub, not implemented)."""

    def __init__(self, *args: Any, **kwargs: Any):
        raise NotImplementedError(
            "External JSON-2 API backend is not implemented yet ; "
            "use the jsonrpc backend or contribute the JSON-2 mapping in "
            f"{jsonrpc.__name__}"
        )
