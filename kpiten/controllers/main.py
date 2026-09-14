import logging

from odoo.http import Controller, Response, request, route

logger = logging.getLogger(__name__)


class kpiten(Controller):
    @route("/kpiten/cmp/<string:uuid>", type="http", auth="user")
    def _compare_UUID(self, uuid, **kwargs):
        env = request.env
        res = env["res.users.log"].search([("uuid", "=", uuid)])
        user = res.create_uid

        if user:
            return Response(status=200)
        else:
            return Response(status=500)

    # NOTE : data and metadata are no longer POSTed here ; the external app
    #        reads them through the jsonrpc channel (see model `kpiten`).
    #        A future /kpiten/<model> stub may route to Odoo >= 19 External
    #        JSON-2 API backend without keeping this payload protocol.
