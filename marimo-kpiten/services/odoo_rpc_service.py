from services.env_reader_service import EnvReaderService
import logging
import odoorpc

EnvReader = EnvReaderService()
logger = logging.getLogger(__name__)

import requests

class OdooRPCService:
    _instance = None

    def __init__(self):
        self._HOST = EnvReader.get("ODOO_SERVER_HOST") or "localhost"
        self._PORT = EnvReader.get("ODOO_SERVER_PORT") or 8069
        self._DB = EnvReader.get("ODOO_DB_NAME") or "db"
        self._ODOO_UNAME = EnvReader.get("ODOO_UNAME") or "odoo"
        self._ODOO_PWD = EnvReader.get("ODOO_PWD") or "odoo"
        self._odoo = odoorpc.ODOO(self._HOST, port=self._PORT)
    

    def enable(self):
        self._odoo.login(self._DB, self._ODOO_UNAME, self._ODOO_PWD)

    def check_uuid(self, uuid: str) -> bool:
        odoo = self._odoo
        res = odoo.env["res.users.log" ""].search([("uuid", "=", uuid)])

        return res != []

    def get_uinfo(self):
        user = self._odoo.env.user
        return {"name": user.name, "company": user.company_id.name}

    def disable(self):
        return self.odoo.logout()

    def get_odoo_env(self):
        return self.odoo

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
