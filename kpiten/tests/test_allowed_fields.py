from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAllowedFields(TransactionCase):
    def test_a_field_restricted_by_groups_is_not_allowed(self):
        """`ir.actions.server.code` is for the administrators : an internal user
        gets no such column, whatever the model ACL says."""
        internal = self.env["res.users"].create(
            {
                "name": "Internal",
                "login": "internal-kt",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        admin_fields = self.env["kt"].get_allowed_fields(
            "ir.actions.server", self.env.ref("base.user_admin").id
        )
        user_fields = self.env["kt"].get_allowed_fields(
            "ir.actions.server", internal.id
        )
        self.assertIn("code", admin_fields)
        self.assertNotIn("code", user_fields)
        self.assertIn("name", user_fields)  # the others are still there
