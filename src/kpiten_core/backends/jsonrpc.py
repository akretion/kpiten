"""Odoo access through the legacy JSON-RPC / XML-RPC (odoorpc).

The API kept here is intended to stay small and transport agnostic so a
future json-2 backend (Odoo >= 19 External API) can implement the same
methods.
"""

import json
import logging

import odoorpc

from kpiten_core import env

logger = logging.getLogger(__name__)


def _parse_filter_config(raw):
    if not raw:
        return {}
    return json.loads(raw)


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
        """Validate a user uuid (res.users.log), return user_id or None."""
        log_ids = self.env["res.users.log"].search([("uuid", "=", uuid)])
        if not log_ids:
            return None
        log = self.env["res.users.log"].browse(log_ids[0])
        return log.create_uid.id

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
        rec["filter_config"] = _parse_filter_config(rec["filter_config"])
        return rec

    def get_chart_config(self) -> dict:
        """Chart default styling from the single kt.config record.

        i.e. {"graph": {"layout": {"colorway": ["#00dc82", "#34cdfe"]}}}
        """
        if self.env["ir.model"].search([("model", "=", "kt.config")]):
            return self.env["kt.config"].get_config_json()
        return {}

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
        line = self.env["kt.dataset.line"]
        records = line.search_read(
            domain,
            fields=[
                "id",
                "dataset_id",
                "definition",
                "name",
                "kind",
                "col_span",
                "tile_height",
            ],
        )
        return [
            {
                "id": rec["id"],
                "dataset_id": rec["dataset_id"],
                "content": rec["definition"],
                "name": rec["name"],
                "kind": rec["kind"],
                "col_span": rec["col_span"],
                "tile_height": rec["tile_height"],
            }
            for rec in records
        ]

    def get_conf_id(self, model: str) -> int | None:
        return self.env["kt.dataset.line"].get_conf_id(model)

    def get_panel_tiles(self, panel_id: int, user_id: int) -> list[dict]:
        """All tiles of a panel, whatever the dataset model, with layout info."""
        line = self.env["kt.dataset.line"]
        lines = line.search_read(
            [("panel_id", "=", panel_id)],
            fields=[
                "id",
                "dataset_id",
                "definition",
                "name",
                "kind",
                "col_span",
                "tile_height",
            ],
        )
        if not lines:
            return []
        dataset_ids = [l["dataset_id"][0] for l in lines]
        datasets = self.env["kt.dataset"].read(dataset_ids, ["model_id"])
        models: dict[int, str] = {}
        for ds in datasets:
            ir_model = self.env["ir.model"].browse(ds["model_id"][0])
            models[ds["id"]] = ir_model.model
        return [
            {
                "id": rec["id"],
                "dataset_id": rec["dataset_id"][0],
                "model": models[rec["dataset_id"][0]],
                "content": rec["definition"],
                "name": rec["name"],
                "kind": rec["kind"],
                "col_span": rec["col_span"],
                "tile_height": rec["tile_height"],
            }
            for rec in lines
        ]

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

    def get_record_vals(
        self,
        model: str,
        domain: list,
        user_id: int,
        limit: int | None = None,
        offset: int = 0,
        order: str = "",
    ) -> list[dict]:
        return self.env["kt"].get_record_vals(
            model, domain, user_id, limit, offset, order
        )

    def get_max_create_date(self, model: str, user_id: int) -> str | None:
        """Most recent create_date of a model, None if the table is empty."""
        value = self.env["kt"].get_max_create_date(model, user_id)
        return value if value else None

    def get_count(self, model: str, domain: list, user_id: int) -> int:
        """Number of records matching `domain` (search_count)."""
        return self.env["kt"].get_count(model, domain, user_id)

    def get_staging_dir(self) -> str:
        """Shared-volume dir where Odoo dumps JSONL staging chunks."""
        return self.env["kt"].get_staging_dir()

    def write_staging_chunk(
        self,
        model: str,
        offset: int,
        limit: int,
        domain: list = None,
        order: str = "",
        user_id: int = None,
    ) -> int:
        """Ask Odoo to fetch a chunk and append it as JSONL in its staging dir."""
        return self.env["kt"].write_staging_chunk(
            model, offset, limit, domain, order, user_id=user_id
        )

    def get_deletions(self, model: str, since: str) -> list[int]:
        """Ids of records deleted after `since` (module auditlog)."""
        ir_model = self.env["ir.model"].search([("model", "=", model)])
        if not ir_model or not self.env["ir.model"].search(
            [("model", "=", "auditlog.log")]
        ):
            return []
        logs = self.env["auditlog.log"].search_read(
            [
                ("model_id", "=", ir_model.id),
                ("method", "=", "unlink"),
                ("create_date", ">", since),
            ],
            fields=["res_id"],
        )
        return [log["res_id"] for log in logs if log["res_id"]]

    def get_fields_metadata(self, model: str) -> dict:
        return self.env["kt"].get_fields_metadata(model)

    def get_sql_query(self, model: str, domain: list = None, order: str = "") -> str:
        """SELECT reading `model` straight from Postgres (see kt module)."""
        return self.env["kt"].get_sql_query(model, domain or [], order)

    def get_view_name(self, model: str) -> str:
        """Persistent SQL view name for `model` (see kt module)."""
        return self.env["kt"].create_sql_view(model)

    def get_allowed_fields(self, model: str, user_id: int) -> list[str]:
        return self.env["kt"].get_allowed_fields(model, user_id)

    def get_user_lang(self, user_id: int) -> str:
        return self.env["res.users"].browse(user_id).lang

    def get_user_tz(self, user_id: int) -> str | None:
        return self.env["res.users"].browse(user_id).tz or None
