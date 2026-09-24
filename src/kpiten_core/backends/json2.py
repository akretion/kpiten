"""Odoo access through the External JSON-2 API (Odoo 19 and after).

`POST /json/2/<model>/<method>` : the arguments are named (`ids`, `context` and the
parameters of the method), the caller is the owner of an API key (header
`Authorization: bearer <key>`), the database is a header too. Odoo announced the
end of the JSON-RPC / XML-RPC API that `jsonrpc.py` (odoorpc) uses.

    ODOO_API=json2
    ODOO_API_KEY=...        # an API key of ODOO_LOGIN (Preferences > Security)

The methods are the ones of `JsonrpcBackend`, for the fronts nothing changes.
"""

import logging

import requests

from kpiten_core import env
from kpiten_core.backends.common import parse_filter_config, tile_dict, tile_fields

logger = logging.getLogger(__name__)

# (database, model) -> id of the Odoo action that lists records by ids
_RECORDS_ACTIONS: dict[tuple[str, str], int] = {}


class Json2Error(Exception):
    """An error Odoo answered (its message) : access, missing record, bad call..."""


class Json2Backend:
    """Read Odoo data & kpiten config through the JSON-2 API."""

    def __init__(self, db: str | None = None):
        self.db = db or env.get("ODOO_DB")
        self.url = f"http://{env.get('ODOO_HOST')}:{env.get('ODOO_PORT')}"
        key = env.get("ODOO_API_KEY")
        if not key:
            raise Json2Error("ODOO_API_KEY is required by the json2 backend")
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"bearer {key}", "X-Odoo-Database": self.db}
        )
        self._user_id: int | None = None
        self._fields: list[str] | None = None  # the tile fields the module has
        if not self.call(
            "ir.model", "search_count", domain=[("model", "=", "kt.panel")]
        ):
            raise Exception(f"Kpiten module not installed in '{self.db}' db")

    def call(self, model: str, method: str, /, ids: list[int] | None = None, **kwargs):
        """`model.method(**kwargs)` on `ids` (none : an `@api.model` method)."""
        payload = dict(kwargs)
        if ids:
            payload["ids"] = list(ids)
        response = self.session.post(
            f"{self.url}/json/2/{model}/{method}",
            json=payload,
            timeout=env.odoo_timeout,
        )
        if response.status_code != 200:
            try:
                message = response.json().get("message")
            except ValueError:
                message = response.text[:300]
            raise Json2Error(f"{model}.{method} : {message} ({response.status_code})")
        return response.json()

    # ---- databases ----------------------------------------------------
    def list_databases(self) -> list[str]:
        """Database names served by this odoo instance."""
        resp = requests.post(f"{self.url}/web/database/list", json={}, timeout=5)
        return resp.json().get("result", [])

    # ---- the users ----------------------------------------------------
    def current_user_id(self) -> int:
        """The Odoo user of the API key (ODOO_LOGIN)."""
        if self._user_id is None:
            ids = self.call(
                "res.users", "search", domain=[("login", "=", env.get("ODOO_LOGIN"))]
            )
            if not ids:
                raise Json2Error(f"no user {env.get('ODOO_LOGIN')} in {self.db}")
            self._user_id = ids[0]
        return self._user_id

    def _user(self, user_id: int, field: str):
        rows = self.call("res.users", "read", ids=[user_id], fields=[field])
        return rows[0][field] if rows else None

    def get_user_name(self, user_id: int) -> str:
        return self._user(user_id, "name")

    def get_user_lang(self, user_id: int) -> str:
        return self._user(user_id, "lang")

    def get_user_tz(self, user_id: int) -> str | None:
        return self._user(user_id, "tz") or None

    # ---- auth ---------------------------------------------------------
    def check_uuid(self, uuid: str) -> int | None:
        """The user id of a valid uuid, else None (`kt.check_uuid`)."""
        try:
            return self.call("kt", "check_uuid", user_uuid=uuid) or None
        except Exception:
            logger.exception("check_uuid failed")
            return None

    # ---- kpiten config ------------------------------------------------
    def get_panels(self) -> list[dict]:
        records = self.call(
            "kt.panel",
            "search_read",
            domain=[],
            fields=["id", "name"],
            order="sequence, id",
        )
        return [{"id": rec["id"], "name": rec["name"]} for rec in records]

    def get_panel_settings(self, panel_id: int) -> dict:
        rec = self.call(
            "kt.panel", "read", ids=[panel_id], fields=["id", "name", "filter_config"]
        )[0]
        rec["filter_config"] = parse_filter_config(rec["filter_config"])
        return rec

    def get_chart_config(self) -> dict:
        return self.call("kt.config", "get_config_json")

    def get_user_theme(self, user_id: int) -> str | None:
        try:
            return self.call("kt.config", "get_user_theme", user_id=user_id) or None
        except Exception:
            logger.exception("get_user_theme(%s) failed", user_id)
            return None

    def set_user_theme(self, user_id: int, theme: str | None) -> None:
        try:
            self.call(
                "kt.config", "set_user_theme", user_id=user_id, theme=theme or False
            )
        except Exception:
            logger.exception("set_user_theme(%s, %s) failed", user_id, theme)

    def _model_names(self, dataset_ids) -> dict[int, str]:
        """dataset id -> the technical name of its model."""
        datasets = self.call(
            "kt.dataset", "read", ids=list(set(dataset_ids)), fields=["model_id"]
        )
        model_ids = {ds["model_id"][0] for ds in datasets}
        names = {
            m["id"]: m["model"]
            for m in self.call(
                "ir.model", "read", ids=list(model_ids), fields=["model"]
            )
        }
        return {ds["id"]: names[ds["model_id"][0]] for ds in datasets}

    def get_panel_lines(self, model: str, panel_id: int | None = None) -> list[dict]:
        domain = [("dataset_id.model_id.model", "=", model)]
        if panel_id:
            domain.append(("panel_id", "=", panel_id))
        records = self.call(
            "kt.dataset.line", "search_read", domain=domain, fields=self._tile_fields()
        )
        return [tile_dict(rec) for rec in records]

    def _tile_fields(self) -> list[str]:
        if self._fields is None:
            self._fields = tile_fields(
                lambda names: self.call(
                    "kt.dataset.line",
                    "fields_get",
                    allfields=names,
                    attributes=["type"],
                )
            )
        return self._fields

    def get_conf_id(self, model: str) -> int | None:
        return self.call("kt.dataset.line", "get_conf_id", model=model)

    def get_panel_tiles(self, panel_id: int, user_id: int) -> list[dict]:
        """All tiles of a panel, whatever the dataset model, with layout info."""
        lines = self.call(
            "kt.dataset.line",
            "search_read",
            domain=[("panel_id", "=", panel_id)],
            fields=self._tile_fields(),
        )
        if not lines:
            return []
        models = self._model_names(l["dataset_id"][0] for l in lines)
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
        return self.call(
            "kt.dataset.line",
            "create_tile",
            model=model,
            definition=definition,
            kind=kind,
            name=name,
            user_id=user_id,
            panel_id=panel_id,
        )

    def get_records_action_id(self, model: str) -> int:
        key = (self.db, model)
        if key not in _RECORDS_ACTIONS:
            _RECORDS_ACTIONS[key] = self.call("kt", "get_records_action", model=model)
        return _RECORDS_ACTIONS[key]

    def can_edit_tiles(self, user_id: int) -> bool:
        """Closed on any error : no edit mode without a clear yes from Odoo."""
        try:
            return bool(self.call("kt", "can_edit_tiles", user_id=user_id))
        except Exception:
            logger.exception("can_edit_tiles(%s) failed", user_id)
            return False

    def delete_tile(self, line_id: int) -> None:
        self.call("kt.dataset.line", "unlink", ids=[line_id])

    def update_tile_layout(self, line_id: int, col_span: int, tile_height: int) -> None:
        self.call(
            "kt.dataset.line",
            "write",
            ids=[line_id],
            vals={"col_span": col_span, "tile_height": tile_height},
        )

    def update_tile_order(self, line_ids: list[int]) -> None:
        for sequence, line_id in enumerate(line_ids):
            self.call(
                "kt.dataset.line", "write", ids=[line_id], vals={"sequence": sequence}
            )

    # ---- data access --------------------------------------------------
    def get_dataset_models(self) -> list[str]:
        ids = self.call("kt.dataset", "search", domain=[])
        return list(self._model_names(ids).values()) if ids else []

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
        return self.call("kt", "get_fields_metadata", model=model)

    def get_sql_query(self, model: str, domain: list = None, order: str = "") -> str:
        return self.call(
            "kt", "get_sql_query", model=model, domain=domain or [], order=order
        )

    def get_view_name(self, model: str) -> str:
        return self.call("kt", "create_sql_view", model=model)

    def get_display_names(self, model: str, ids: list[int]) -> dict[int, str]:
        """Bulk-resolve `ids` of `model` to their `display_name` (the ids of deleted
        records are skipped by `read`)."""
        if not ids:
            return {}
        records = self.call(model, "read", ids=list(ids), fields=["display_name"])
        return {rec["id"]: rec["display_name"] for rec in records}

    def get_base_url(self) -> str:
        try:  # `get_str` from Odoo 20, `get_param` before
            url = self.call("ir.config_parameter", "get_str", key="web.base.url")
        except Json2Error:
            url = self.call("ir.config_parameter", "get_param", key="web.base.url")
        return (url or self.url).rstrip("/")

    def get_allowed_fields(self, model: str, user_id: int) -> list[str]:
        return self.call("kt", "get_allowed_fields", model=model, allowed_uid=user_id)

    def get_access_query(self, model: str, user_id: int) -> str:
        return self.call("kt", "get_access_query", model=model, user_id=user_id)
