"""Backend abstraction to talk to Odoo.

Two implementations are planned :
- `jsonrpc` : current JSON-RPC / XML-RPC channel (odoorpc), Odoo <= 18.
- `json2`   : Odoo >= 19 External JSON-2 API (not implemented yet).
"""

from typing import Any

from kpiten_core.backends.jsonrpc import JsonrpcBackend
from kpiten_core.backends.json2 import Json2Backend

BACKENDS = {"jsonrpc": JsonrpcBackend, "json2": Json2Backend}


class Backend:
    """Odoo access layer used by the UI apps.

    The abstract API is intentionally transport agnostic so a future
    Odoo >= 19 JSON-2 backend can be added without touching the apps.
    """

    def __init__(self):
        raise NotImplementedError("use Backend.create(protocol) instead")

    @classmethod
    def create(cls, protocol: str = "jsonrpc", db: str | None = None) -> Any:
        return BACKENDS[protocol](db=db)

    # ---- generic data access ------------------------------------------
    def get_dataset_models(self) -> list[str]:
        """Technical names of the models declared as kt.dataset."""
        raise NotImplementedError

    def get_record_vals(
        self,
        model: str,
        domain: list,
        user_id: int,
        limit: int | None = None,
        offset: int = 0,
        order: str = "",
    ) -> list[dict]:
        raise NotImplementedError

    def get_max_create_date(self, model: str, user_id: int) -> str | None:
        """Most recent create_date of a model (None if the table is empty)."""
        raise NotImplementedError

    def get_count(self, model: str, domain: list, user_id: int) -> int:
        """Number of records matching `domain` (search_count)."""
        raise NotImplementedError

    def get_fields_metadata(self, model: str) -> dict:
        raise NotImplementedError

    def get_chart_config(self) -> dict:
        """Chart defaults stored in odoo (ir.config_parameter kt_config)."""
        raise NotImplementedError

    def get_allowed_fields(self, model: str, user_id: int) -> list[str]:
        raise NotImplementedError

    def get_user_lang(self, user_id: int) -> str:
        raise NotImplementedError

    def get_user_tz(self, user_id: int) -> str | None:
        """IANA timezone of the user (res.users.tz), None if unset."""
        raise NotImplementedError

    # ---- kpiten config ------------------------------------------------
    def get_panels_settings(self) -> list[dict]:
        """Fetch kt.panel records."""
        raise NotImplementedError

    def get_panel_lines(self, model: str, panel_id: int | None = None) -> list[dict]:
        """Fetch kt.dataset.line records for a model / panel."""
        raise NotImplementedError

    def get_panel_tiles(self, panel_id: int, user_id: int) -> list[dict]:
        """Fetch all tiles of a panel, each with its dataset technical model name."""
        raise NotImplementedError

    def create_tile(
        self,
        model: str,
        definition: str,
        kind: str,
        name: str | None = None,
        user_id: int | None = None,
        panel_id: int | None = None,
    ) -> bool:
        raise NotImplementedError

    def delete_tile(self, line_id: int) -> None:
        raise NotImplementedError

    def update_tile_layout(self, line_id: int, col_span: int, tile_height: int) -> None:
        """Store the grid layout of a tile (edit mode drag/resize)."""
        raise NotImplementedError

    def update_tile_order(self, line_ids: list[int]) -> None:
        """Store the tiles sequence of a panel (index in `line_ids`)."""
        raise NotImplementedError

    # ---- auth ---------------------------------------------------------
    def check_uuid(self, uuid: str) -> dict | None:
        """Validate a user uuid, return user info or None."""
        raise NotImplementedError


BACKEND = JsonrpcBackend
