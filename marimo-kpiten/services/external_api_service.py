import xmlrpc.client
from services.env_reader_service import EnvReaderService


def xml_rpc_test():
    env_service = EnvReaderService()

    url = "http://localhost:8070"
    db = "odoo18"
    username = "admin"
    password = env_service.get("ODOO_API_KEY")

    common = xmlrpc.client.ServerProxy("{}/xmlrpc/2/common".format(url))
    print(common.version())

    uid = common.authenticate(db, username, password, {})

    models = xmlrpc.client.ServerProxy("{}/xmlrpc/2/object".format(url))
    o = models.execute_kw(
        db, uid, password, "res.partner", "name_search", ["foo"], {"limit": 10}
    )

    print(o)
