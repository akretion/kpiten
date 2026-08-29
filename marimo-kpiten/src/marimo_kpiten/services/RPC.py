import odoorpc
from odoorpc.env import Environment
from odoorpc import ODOO
from marimo_kpiten.services.env_reader import EnvReader as env_


class RPC:
    _instance = None
    odoo: ODOO | None = None
    env: Environment | None = None

    def __new__(cls, *args, **kargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self.odoo is None:
            self.connect()

    def connect(self):
        self.odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))
        self.odoo.login(
            env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD")
        )
        if not self.odoo:
            raise ConnectionError("(RPC CLASS) : Odoorpc did not initialize properly.")
        self.env = self.odoo.env
