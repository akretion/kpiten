"""Env for the e2e tests: Odoo access + absolute parquet dir."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for key, value in {
    "ODOO_HOST": "localhost",
    "ODOO_PORT": "8069",
    "ODOO_DB": "kpiten",
    "ODOO_LOGIN": "admin",
    "ODOO_PWD": "admin",
    "DATA_PATH": str(ROOT / "data_dir"),
}.items():
    os.environ.setdefault(key, value)
