import re

from odoo import _, api, exceptions, fields, models

from ..compat import is_sql

# the name a query reads the table by : a SQL identifier, no dot (the tables of the
# store have one : `sale.order`), and never `d` (the table chosen in the front)
NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
RESERVED = {"d", "self"}


class KtDerivedTable(models.Model):
    """A table computed from the datasets by a SQL query (a chain of CTE, one step
    each), that the fronts run on the rows of each user : a derived table shared by a
    KpiTen manager shows every user their own rows only.

    Personal to its owner, or shared (by a KpiTen manager only : see the record
    rules). The fronts read and save them through `list_for` and `save_for`.
    """

    _name = "kt.derived.table"
    _description = "KpiTen derived table"
    _order = "name, id"

    name = fields.Char(
        required=True,
        help="The name a query reads the table by : lowercase letters, digits and _ "
        "(confirmed_sales).",
    )
    description = fields.Char(help="What the table holds, in a sentence.")
    source = fields.Char(
        help="The table of the store the query reads as d (sale.order) ; the others "
        'by their name in double quotes ("sale.order.line").'
    )
    sql = fields.Text(
        string="SQL",
        required=True,
        help="A SELECT, in steps : one WITH block per step, a -- comment above each.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Owner",
        required=True,
        default=lambda self: self.env.user,
        ondelete="cascade",
    )
    shared = fields.Boolean(
        help="Every user may read it (each one sees their own rows). Only a KpiTen "
        "manager shares a table."
    )

    @api.constrains("name")
    def _check_name(self):
        for rec in self:
            if not NAME.match(rec.name or "") or rec.name in RESERVED:
                raise exceptions.ValidationError(
                    _(
                        "%s : the name of a derived table is made of lowercase "
                        "letters, digits and _, and is not d."
                    )
                    % rec.name
                )

    @api.constrains("name", "user_id", "shared")
    def _check_unique(self):
        for rec in self:
            domain = [("id", "!=", rec.id), ("name", "=", rec.name)]
            owner = domain + [("user_id", "=", rec.user_id.id)]
            if self.sudo().search_count(owner) or (
                rec.shared
                and self.sudo().search_count(domain + [("shared", "=", True)])
            ):
                raise exceptions.ValidationError(
                    _("A derived table named %s already exists.") % rec.name
                )

    @api.constrains("sql")
    def _check_sql(self):
        for rec in self:
            if is_sql and not is_sql(rec.sql or ""):
                raise exceptions.ValidationError(
                    _("The SQL of a derived table is a SELECT (or WITH ... SELECT).")
                )

    @api.model
    def _as_user(self, user_id):
        """The model as `user_id` : the fronts call with one RPC account, a KpiTen
        manager ; nobody else may act for another user."""
        user_id = user_id or self.env.uid
        if user_id != self.env.uid and not self.env.user.has_group(
            "kpiten.group_kpiten_manager"
        ):
            raise exceptions.AccessError(
                _("Only a KpiTen manager acts for another user.")
            )
        return self.with_user(user_id)

    @api.model
    def list_for(self, user_id=None) -> list:
        """The derived tables of `user_id` in a front : their own and the shared ones
        (a KpiTen manager reads the others' in Odoo, not in a front)."""
        user_id = user_id or self.env.uid
        return [
            {
                "id": rec.id,
                "name": rec.name,
                "description": rec.description or "",
                "source": rec.source or "",
                "sql": rec.sql,
                "shared": rec.shared,
                "owner": rec.user_id.sudo().name,
                "mine": rec.user_id.id == user_id,
            }
            for rec in self._as_user(user_id).search(
                ["|", ("user_id", "=", user_id), ("shared", "=", True)]
            )
        ]

    @api.model
    def save_for(
        self, user_id, name, sql, description="", shared=False, source=""
    ) -> int:
        """Create, or update, the derived table `name` of `user_id` ; its id."""
        model = self._as_user(user_id)
        values = {
            "sql": sql,
            "description": description,
            "shared": bool(shared),
            "source": source or False,
        }
        record = model.search(
            [("name", "=", name), ("user_id", "=", model.env.uid)], limit=1
        )
        if record:
            record.write(values)
        else:
            record = model.create({**values, "name": name, "user_id": model.env.uid})
        return record.id
