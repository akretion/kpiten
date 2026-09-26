"""Odoo access through the legacy JSON-RPC / XML-RPC (odoorpc).

The API kept here is intended to stay small and transport agnostic so a
future json-2 backend (Odoo >= 19 External API) can implement the same
methods.
"""

import logging

import odoorpc

from kpiten_core import env
from kpiten_core.backends.common import (
    KPI_MODEL,
    LEGACY_KPI_MODEL,
    parse_filter_config,
    read_panel_tiles,
    tile_dict,
    tile_fields,
)

logger = logging.getLogger(__name__)

# (database, model) -> id of the Odoo action that lists records by ids
_RECORDS_ACTIONS: dict[tuple[str, str], int] = {}


class JsonrpcBackend:
    """Read Odoo data & kpiten config through odoorpc."""

    def __init__(self, db: str | None = None):
        self.odoo = odoorpc.ODOO(env.get("ODOO_HOST"), port=env.get("ODOO_PORT"))
        self.odoo.config["timeout"] = env.odoo_timeout
        self.db = db or env.get("ODOO_DB")
        self.odoo.login(self.db, env.get("ODOO_LOGIN"), env.get("ODOO_PWD"))
        self.env = self.odoo.env
        if not self.env["ir.model"].search([("model", "=", "kt.panel")]):
            raise Exception(f"Kpiten module not installed in '{self.env.db}' db")
        # the model of the tiles : `kt.dataset.line` in a base not updated to 1.5.0
        known = self.env["ir.model"].search([("model", "=", KPI_MODEL)])
        self.kpi_model = KPI_MODEL if known else LEGACY_KPI_MODEL

    def call(self, model: str, method: str, /, ids: list[int] | None = None, **kwargs):
        """`model.method(**kwargs)` on `ids` (none : an `@api.model` method), the
        same call as the json2 backend."""
        args = [list(ids)] if ids else []
        return self.odoo.execute_kw(model, method, args, kwargs)

    # ---- databases ----------------------------------------------------
    def list_databases(self) -> list[str]:
        """Database names served by this odoo instance."""
        import requests

        host = env.get("ODOO_HOST")
        port = env.get("ODOO_PORT")
        resp = requests.post(
            f"http://{host}:{port}/web/database/list", json={}, timeout=5
        )
        return resp.json().get("result", [])

    # ---- auth ---------------------------------------------------------
    def check_uuid(self, uuid: str) -> int | None:
        """The user id of a valid uuid, else None. Odoo decides : an uuid older than a
        week (`kpiten_uuid_days`) is refused (`kt.check_uuid`)."""
        try:
            return self.env["kt"].check_uuid(uuid) or None
        except Exception:
            logger.exception("check_uuid failed")
            return None

    # ---- the users ----------------------------------------------------
    def current_user_id(self) -> int:
        """The Odoo user of the backend (ODOO_LOGIN) : the dashboards of the dev
        mode and the sync run as them."""
        return self.env.user.id

    def get_user_name(self, user_id: int) -> str:
        return self.env["res.users"].browse(user_id).name

    # ---- kpiten config ------------------------------------------------
    def get_panels(self) -> list[dict]:
        """Fetch kt.panel records."""
        panel = self.env["kt.panel"]
        records = panel.search_read([], fields=["id", "name"], order="sequence, id")
        return [{"id": rec["id"], "name": rec["name"]} for rec in records]

    def get_panel_settings(self, panel_id: int) -> dict:
        """Return the panel record with filter settings."""
        panel = self.env["kt.panel"]
        rec = panel.search_read(
            [("id", "=", panel_id)],
            fields=["id", "name", "filter_config"],
        )[0]
        rec["filter_config"] = parse_filter_config(rec["filter_config"])
        return rec

    def get_chart_config(self) -> dict:
        """Chart default styling from the single kt.config record.

        i.e. {"graph": {"layout": {"colorway": ["#00dc82", "#34cdfe"]}}}
        """
        if self.env["ir.model"].search([("model", "=", "kt.config")]):
            return self.env["kt.config"].get_config_json()
        return {}

    def get_user_theme(self, user_id: int) -> str | None:
        """The theme the user chose (`kt.user.theme`), None when they chose none or
        when the kpiten module is older."""
        try:
            return self.env["kt.config"].get_user_theme(user_id) or None
        except Exception:
            logger.exception("get_user_theme(%s) failed", user_id)
            return None

    def set_user_theme(self, user_id: int, theme: str | None) -> None:
        """Keep in Odoo the theme the user chose ; None forgets it."""
        try:
            self.env["kt.config"].set_user_theme(user_id, theme or False)
        except Exception:
            logger.exception("set_user_theme(%s, %s) failed", user_id, theme)

    def get_panel_lines(self, model: str, panel_id: int | None = None) -> list[dict]:
        """Fetch the tiles (`kt.kpi`) of a model, optionally a panel."""
        model_id = self.env["ir.model"].search([("model", "=", model)])
        if not model_id:
            raise Exception(f"No kt.dataset for model '{model}'")
        dataset = self.env["kt.dataset"].search([("model_id", "=", model_id)])
        if not dataset:
            raise Exception(f"No kt.dataset for model '{model}'")
        dataset_id = dataset[0]
        domain = [("dataset_id", "=", dataset_id)]
        if panel_id:
            domain.append(("panel_ids", "in", [panel_id]))
        records = self.env[self.kpi_model].search_read(
            domain, fields=self._tile_fields()
        )
        return [tile_dict(rec) for rec in records]

    def _tile_fields(self) -> list[str]:
        """The tile fields the module has (an older one : not `display`...)."""
        if getattr(self, "_fields", None) is None:
            self._fields = tile_fields(self.env[self.kpi_model].fields_get)
        return self._fields

    def get_conf_id(self, model: str) -> int | None:
        return self.env[self.kpi_model].get_conf_id(model)

    def get_panel_tiles(self, panel_id: int, user_id: int) -> list[dict]:
        """All tiles of a panel, whatever the dataset model, with layout info."""
        return read_panel_tiles(
            self.call, self.kpi_model, self._tile_fields(), panel_id
        )

    # ---- create / delete tiles ----------------------------------------
    def create_tile(
        self,
        model: str,
        definition: str,
        kind: str,
        name: str | None = None,
        user_id: int | None = None,
        panel_id: int | None = None,
        values: dict | None = None,
    ) -> int:
        args = [model, definition, kind, name, user_id, panel_id]
        if values:  # an older kpiten module has no `values`
            args.append(values)
        return self.env[self.kpi_model].create_tile(*args)

    def get_records_action_id(self, model: str) -> int:
        key = (self.db, model)
        if key not in _RECORDS_ACTIONS:  # the action of a model does not change
            _RECORDS_ACTIONS[key] = self.env["kt"].get_records_action(model)
        return _RECORDS_ACTIONS[key]

    def can_edit_tiles(self, user_id: int) -> bool:
        """Closed on any error : no edit mode without a clear yes from Odoo."""
        try:
            return bool(self.env["kt"].can_edit_tiles(user_id))
        except Exception:
            logger.exception("can_edit_tiles(%s) failed", user_id)
            return False

    def get_derived_tables(self, user_id: int) -> list[dict]:
        try:
            return self.call("kt.derived.table", "list_for", user_id=user_id)
        except Exception:  # an older kpiten module : no derived tables
            logger.exception("get_derived_tables(%s) failed", user_id)
            return []

    def save_derived_table(
        self,
        user_id: int,
        name: str,
        sql: str,
        description: str = "",
        shared: bool = False,
        source: str = "",
        language: str = "sql",
    ) -> int:
        return self.call(
            "kt.derived.table",
            "save_for",
            user_id=user_id,
            name=name,
            sql=sql,
            description=description,
            shared=shared,
            source=source,
            language=language,
        )

    # the tiles are changed by a bare call, never through `browse` : odoorpc reads every
    # field of a record it browses, the preview of a KPI among them, which asks this
    # very app for a session (`kt._kpiten_session`) while it waits for Odoo : 30 s lost
    # a tile, the app stuck meanwhile
    def remove_tile(self, panel_id: int, line_id: int) -> None:
        self.call("kt.panel", "remove_tiles", ids=[panel_id], kpi_ids=[line_id])

    def update_tile_layout(
        self, panel_id: int, line_id: int, col_span: int, tile_height: int
    ) -> None:
        self.call(
            "kt.panel",
            "set_tile_layout",
            ids=[panel_id],
            kpi_id=line_id,
            col_span=col_span,
            tile_height=tile_height,
        )

    def update_tile_order(self, panel_id: int, line_ids: list[int]) -> None:
        self.call("kt.panel", "set_tile_order", ids=[panel_id], kpi_ids=line_ids)

    # ---- data access --------------------------------------------------
    def get_dataset_models(self) -> list[str]:
        """Technical names of all models declared as kt.dataset."""
        dataset = self.env["kt.dataset"]
        datasets = dataset.search_read([], fields=["model_id"])
        return [self.env["ir.model"].browse(ds["model_id"][0]).model for ds in datasets]

    def get_field_labels(self, model: str, lang: str | None = None) -> dict[str, str]:
        """{field: its label in Odoo}, in `lang` (the one of the backend's user
        without it)."""
        context = {"lang": lang} if lang else {}
        rows = self.call(
            "ir.model.fields",
            "search_read",
            domain=[("model", "=", model)],
            fields=["name", "field_description"],
            context=context,
        )
        return {row["name"]: row["field_description"] for row in rows}

    def get_fields_metadata(self, model: str) -> dict:
        return self.env["kt"].get_fields_metadata(model)

    def get_sql_query(self, model: str, domain: list = None, order: str = "") -> str:
        """SELECT reading `model` straight from Postgres (see kt module)."""
        return self.env["kt"].get_sql_query(model, domain or [], order)

    def get_view_name(self, model: str) -> str:
        """Persistent SQL view name for `model` (see kt module)."""
        return self.env["kt"].create_sql_view(model)

    def get_display_names(self, model: str, ids: list[int]) -> dict[int, str]:
        """Bulk-resolve `ids` of `model` to their `display_name`.

        One batched `read`, so models overriding `name_get`/`display_name`
        are resolved correctly (unlike a SQL guess of the "right" text
        column). `read` silently skips ids of records deleted since the m2o
        column was extracted.
        """
        if not ids:
            return {}
        records = self.env[model].read(list(ids), ["display_name"])
        return {rec["id"]: rec["display_name"] for rec in records}

    def get_base_url(self) -> str:
        url = self.env["ir.config_parameter"].get_param("web.base.url")
        return (url or f"http://{env.get('ODOO_HOST')}:{env.get('ODOO_PORT')}").rstrip(
            "/"
        )

    def get_allowed_fields(self, model: str, user_id: int) -> list[str]:
        return self.env["kt"].get_allowed_fields(model, user_id)

    def get_access_query(self, model: str, user_id: int) -> str:
        return self.env["kt"].get_access_query(model, user_id)

    def get_user_lang(self, user_id: int) -> str:
        return self.env["res.users"].browse(user_id).lang

    def get_user_tz(self, user_id: int) -> str | None:
        return self.env["res.users"].browse(user_id).tz or None
