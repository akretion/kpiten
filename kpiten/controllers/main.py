import logging

from odoo.http import Controller, Response, request, route

logger = logging.getLogger(__name__)


class kpiten(Controller):
    @route("/kpiten/cmp/<string:uuid>", type="http", auth="user")
    def _compare_UUID(self, uuid, **kwargs):
        user = request.env["res.users.log"]._valid_uuid_user(uuid)

        if user:
            return Response(status=200)
        else:
            return Response(status=500)
