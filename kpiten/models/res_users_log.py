import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.sql import column_exists

UUID_DAYS = 7  # a uuid is valid for a week, then renewed (see `kpiten_uuid_days`)


class ResUsersLog(models.Model):
    """The uuid of a login : what Odoo sends to the dashboard apps to prove who clicks.

    It lives one week (`kpiten_uuid_days` system parameter). The one used by the
    SSO is renewed when it is older, a weekly cron clears the expired ones, and the
    apps ask `kt.check_uuid` which refuses an expired uuid.
    """

    _inherit = "res.users.log"

    uuid = fields.Char(default=lambda self: str(uuid.uuid4()))
    uuid_date = fields.Datetime(
        default=fields.Datetime.now, help="When the uuid was issued."
    )

    def _auto_init(self):
        """The uuids that exist before the column are dated by their login : the old
        ones, that never expired, are refused from now on."""
        existed = column_exists(self.env.cr, "res_users_log", "uuid_date")
        res = super()._auto_init()
        if not existed:
            self.env.cr.execute("UPDATE res_users_log SET uuid_date = create_date")
        return res

    @api.model
    def _uuid_cutoff(self):
        """The oldest date a valid uuid may have been issued."""
        days = int(
            self.env["ir.config_parameter"].sudo().get_param("kpiten_uuid_days")
            or UUID_DAYS
        )
        return fields.Datetime.now() - timedelta(days=days)

    def _uuid_is_valid(self):
        self.ensure_one()
        return bool(
            self.uuid and self.uuid_date and self.uuid_date >= self._uuid_cutoff()
        )

    def _renew_uuid(self):
        """A new uuid, valid for a week from now."""
        for log in self:
            log.write({"uuid": str(uuid.uuid4()), "uuid_date": fields.Datetime.now()})

    @api.model
    def _valid_uuid_user(self, user_uuid):
        """The user a valid (not expired) uuid belongs to, else False."""
        if not user_uuid:
            return False
        log = self.sudo().search(
            [("uuid", "=", user_uuid), ("uuid_date", ">=", self._uuid_cutoff())],
            limit=1,
        )
        # create_uid is a record on the recent series, a bare id on the oldest
        user = log.create_uid
        return getattr(user, "id", user) or False

    @api.model
    def _cron_renew_uuids(self):
        """Weekly : an expired uuid is cleared, nobody can use it any more. The next
        SSO of the user issues a new one (`kt.action_redirect_to_kpiten`)."""
        expired = self.sudo().search(
            [
                ("uuid", "!=", False),
                "|",
                ("uuid_date", "=", False),
                ("uuid_date", "<", self._uuid_cutoff()),
            ]
        )
        expired.write({"uuid": False})
        return len(expired)
