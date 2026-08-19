import odoorpc

from marimo_kpiten.services.env_reader import EnvReader


def _get_config_model(env):
    """
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    if not env["ir.model"].search([("model", "=", "kpiten.config")]):
        raise Exception(f"Kpiten module not installed in '{odoo.env.db}' db")
    return env["kpiten.config.line"]


def _get_odoo_env():
    env_ = EnvReader()
    odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))
    odoo.login(env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD"))
    return odoo.env
