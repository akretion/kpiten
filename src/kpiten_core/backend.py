"""Backend abstraction to talk to Odoo.

Two implementations, chosen by `ODOO_API` (the environment, `jsonrpc` by default) :
- `jsonrpc` : the JSON-RPC / XML-RPC channel (odoorpc), Odoo 14 to 18.
- `json2`   : the External JSON-2 API (an API key : `ODOO_API_KEY`), Odoo 19 and after.
"""

from typing import Any

from kpiten_core import env

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
    def create(cls, protocol: str | None = None, db: str | None = None) -> Any:
        return BACKENDS[protocol or env.get("ODOO_API") or "jsonrpc"](db=db)

    # ---- the users ----------------------------------------------------
    def current_user_id(self) -> int:
        """The Odoo user of the backend (ODOO_LOGIN) : the dev mode, the sync."""
        raise NotImplementedError

    def get_user_name(self, user_id: int) -> str:
        raise NotImplementedError

    # ---- generic data access ------------------------------------------
    def get_dataset_models(self) -> list[str]:
        """Technical names of the models declared as kt.dataset."""
        raise NotImplementedError

    def get_fields_metadata(self, model: str) -> dict:
        raise NotImplementedError

    def get_sql_query(self, model: str, domain: list = None, order: str = "") -> str:
        """SELECT reading `model` straight from Postgres (direct extraction)."""
        raise NotImplementedError

    def get_view_name(self, model: str) -> str:
        """Name of the persistent SQL view exposing `model` (view mode)."""
        raise NotImplementedError

    def get_display_names(self, model: str, ids: list[int]) -> dict[int, str]:
        """Bulk-resolve `ids` of `model` to their Odoo display_name.

        Used by the direct-SQL extraction path (`sql`/`view` modes) to turn
        the bare foreign keys `kt.get_sql_query` emits back into the same
        display name the ORM would have produced (see `kpiten_core.resolve`).
        """
        raise NotImplementedError

    def get_chart_config(self) -> dict:
        """Chart defaults stored in odoo (ir.config_parameter kt_config)."""
        raise NotImplementedError

    def get_base_url(self) -> str:
        """Public base url of Odoo (ir.config_parameter web.base.url), the
        target of the links from a tile to an Odoo record."""
        raise NotImplementedError

    def get_allowed_fields(self, model: str, user_id: int) -> list[str]:
        raise NotImplementedError

    def get_access_query(self, model: str, user_id: int) -> str:
        """SQL `SELECT id` of the records of `model` the user may read, with
        Odoo's record rules (ir.rule) applied. Empty string : no access."""
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

    def get_records_action_id(self, model: str) -> int:
        """The id of the Odoo list action that opens the records whose ids it is given
        (`/odoo/action-<id>?active_ids=1,2,3`), one per model."""
        raise NotImplementedError

    def can_edit_tiles(self, user_id: int) -> bool:
        """Whether the user may use the edit mode (a KpiTen manager in Odoo)."""
        raise NotImplementedError

    def get_user_theme(self, user_id: int) -> str | None:
        """The theme the user chose in an app (kept in Odoo), None when none."""
        raise NotImplementedError

    def set_user_theme(self, user_id: int, theme: str | None) -> None:
        """Keep in Odoo the theme the user chose ; None forgets it."""
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
