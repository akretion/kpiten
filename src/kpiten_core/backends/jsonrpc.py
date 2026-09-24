"""Odoo access through the legacy JSON-RPC / XML-RPC (odoorpc).

The API kept here is intended to stay small and transport agnostic so a
future json-2 backend (Odoo >= 19 External API) can implement the same
methods.
"""

import logging

import odoorpc

from kpiten_core import env
from kpiten_core.backends.common import TILE_FIELDS, parse_filter_config, tile_dict

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
        """Fetch kt.dataset.line records for a model, optionally a panel."""
        model_id = self.env["ir.model"].search([("model", "=", model)])
        if not model_id:
            raise Exception(f"No kt.dataset for model '{model}'")
        dataset = self.env["kt.dataset"].search([("model_id", "=", model_id)])
        if not dataset:
            raise Exception(f"No kt.dataset for model '{model}'")
        dataset_id = dataset[0]
        domain = [("dataset_id", "=", dataset_id)]
        if panel_id:
            domain.append(("panel_id", "=", panel_id))
        records = self.env["kt.dataset.line"].search_read(domain, fields=TILE_FIELDS)
        return [tile_dict(rec) for rec in records]

    def get_conf_id(self, model: str) -> int | None:
        return self.env["kt.dataset.line"].get_conf_id(model)

    def get_panel_tiles(self, panel_id: int, user_id: int) -> list[dict]:
        """All tiles of a panel, whatever the dataset model, with layout info."""
        line = self.env["kt.dataset.line"]
        names = list(TILE_FIELDS)
        # a kpiten module older than the field : every table is a table
        if "table_view" in line.fields_get(["table_view"]):
            names.append("table_view")
        lines = line.search_read([("panel_id", "=", panel_id)], fields=names)
        if not lines:
            return []
        dataset_ids = [l["dataset_id"][0] for l in lines]
        datasets = self.env["kt.dataset"].read(dataset_ids, ["model_id"])
        models: dict[int, str] = {}
        for ds in datasets:
            ir_model = self.env["ir.model"].browse(ds["model_id"][0])
            models[ds["id"]] = ir_model.model
        return [tile_dict(rec, models[rec["dataset_id"][0]]) for rec in lines]

    # ---- create / delete tiles ----------------------------------------
    def create_tile(
        self,
        model: str,
        definition: str,
        kind: str,
        name: str | None = None,
        user_id: int | None = None,
        panel_id: int | None = None,
    ) -> bool:
        return self.env["kt.dataset.line"].create_tile(
            model, definition, kind, name, user_id, panel_id
        )

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

    def delete_tile(self, line_id: int) -> None:
        self.env["kt.dataset.line"].browse(line_id).unlink()

    def update_tile_layout(self, line_id: int, col_span: int, tile_height: int) -> None:
        self.env["kt.dataset.line"].browse(line_id).write(
            {"col_span": col_span, "tile_height": tile_height}
        )

    def update_tile_order(self, line_ids: list[int]) -> None:
        line = self.env["kt.dataset.line"]
        for sequence, line_id in enumerate(line_ids):
            line.browse(line_id).write({"sequence": sequence})

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
