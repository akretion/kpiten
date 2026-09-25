import json

from odoo import http
from odoo.http import request

from ..compat import SERIES


def parse_ids(text: str) -> list:
    """`1-4,7` -> [1, 2, 3, 4, 7] (see `kpiten_core.odoocheck.id_ranges`)."""
    ids = []
    for part in filter(None, text.split(",")):
        low, _sep, high = part.partition("-")
        ids += range(int(low), int(high or low) + 1)
    return ids


class KpitenCheck(http.Controller):
    @http.route("/kpiten/check", type="http", auth="user", methods=["GET"])
    def check(
        self,
        model,
        name="",
        domain=None,
        ids=None,
        measure=None,
        groupby=None,
        colgroupby=None,
    ):
        """The link « check in Odoo » of a tile : its rows in a pivot, then the
        redirection to it (the user is the one logged in Odoo, with their rights)."""
        if ids is not None:
            domain = [("id", "in", parse_ids(ids))]
        else:
            domain = json.loads(domain or "[]")
            if not isinstance(domain, list):
                raise request.not_found()
        action = request.env["kt"].get_check_action(
            model, name or model, domain, measure, groupby, colgroupby
        )
        if SERIES >= 18:
            return request.redirect(f"/odoo/action-{action}")
        return request.redirect(f"/web#action={action}")
