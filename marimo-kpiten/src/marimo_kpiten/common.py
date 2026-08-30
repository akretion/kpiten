from pathlib import Path

from marimo_kpiten.services.RPC import RPC

DATA_PATH = Path(__file__).resolve().parents[1] / "data_dir"


def _get_odoo_env():
    return RPC().env


def _get_config_model():
    env = _get_odoo_env()
    if not env["ir.model"].search([("model", "=", "kpiten.config")]):
        raise Exception(f"Kpiten module not installed in '{env.db}' db")
    return env["kpiten.config.line"]


def _get_panel_model():
    env = _get_odoo_env()
    if not env["ir.model"].search([("model", "=", "kpiten.panel")]):
        raise Exception(f"Kpiten module not installed in '{env.db}' db")
    return env["kpiten.panel"]
