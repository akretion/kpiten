from __future__ import annotations

import json
import logging

import requests

from odoo import SUPERUSER_ID, api, exceptions, models
from odoo.tools.translate import _

from ..compat import LIST, can_read, ids_sql, readable_fields
from . import kt_sql

# the name of the generic list actions `get_records_action` makes (one per model)
RECORDS_ACTION_NAME = "KpiTen records"

logger = logging.getLogger(__name__)


class Kt(models.AbstractModel):
    _name = "kt"
    _description = "Kt methods"

    def _follow_relational_fields(self):
        """
        for walkable paths only (e.g : some_model.user_id.name)
        [destined to be consumed by odoo's mapped function]

        On top of the paths below, an admin may add more without touching code :
        `kt.config` -> "Relations" tab -> "Other relations" (`_other_relational_fields`).
        """
        fields = {
            "product.product": {
                "default_code",
                "categ_id",
                # the name of the category with its parents (All / Bricolage / Bois) :
                # `categ_id` alone is its id
                "categ_id.complete_name",
                "product_tmpl_id.type",
            },
            "res.partner": {
                "country_id",
                "commercial_partner_id",
                "commercial_partner_id.ref",
            },
            # the order lines get `order_id.date_order` : the period of a panel on lines ;
            # and the rate of the order : their amounts in the currency of the company
            "sale.order": {"date_order", "currency_rate"},
            "purchase.order": {"currency_rate"},
        }
        for model, paths in self._other_relational_fields().items():
            fields[model] = set(fields.get(model, ())) | set(paths)
        return fields

    def _other_relational_fields(self) -> dict:
        """The extra dot-paths an admin added in `kt.config` ("Other relations"), a
        json object validated at save (`kt.config._check_other_relations`).

        `{}` without a config record, or with nothing set there.
        """
        config = self.env["kt.config"].sudo().search([], limit=1)
        if not config or not config.other_relations:
            return {}
        try:
            data = json.loads(config.other_relations)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @api.model
    def get_allowed_fields(self, model: str, allowed_uid: int) -> list[str]:
        stored_fields = (
            self.env["ir.model.fields"]
            .search([("model", "=", model), ("store", "=", True)])
            .mapped("name")
        )
        # `_fields` lists every field of the model : a field restricted by `groups=` is
        # only kept when this user may access it (what `fields_get` does)
        user_env = self.env(user=allowed_uid)
        user_fields = readable_fields(user_env, model)

        additionnal_fields = self._get_relational_paths_for_model(model)

        return [
            *[field for field in user_fields if field in stored_fields],
            *additionnal_fields,
        ]

    @api.model
    def get_access_query(self, model: str, user_id: int) -> str:
        """SQL `SELECT id` of the `model` records `user_id` may read.

        The record rules (ir.rule : own sales only, company...) are applied by
        the ORM itself, so the result is what the user would get in Odoo. It
        is returned as text for kpiten-core, which reads the parquet snapshot
        (extracted straight from Postgres, without any rule) and keeps only
        these rows. An empty string means the user cannot read the model.
        """
        records = self.env[model].with_user(user_id).with_context(active_test=False)
        if not can_read(records):
            return ""
        return ids_sql(records)

    @api.model
    def _get_useless_fields(self, model: str) -> set:
        """The fields of `model` kpiten does not use (not extracted, not offered to a
        tile) : not stored, a list (`*_ids`), a type of `EXCLUDED_FIELD_TYPES`, the
        chatter and the activities (a field towards a `mail.*` model, `mail.message`,
        `mail.activity`..., a field of the mail mixins).

        A module adds its own with `super()._get_useless_fields(model) | {...}`.
        """
        useless = set(
            self.env["ir.model.fields"]
            .search(
                [
                    ("model", "=", model),
                    "|",
                    "|",
                    "|",
                    ("store", "=", False),
                    ("name", "=like", "%_ids"),
                    ("ttype", "in", EXCLUDED_FIELD_TYPES),
                    ("relation", "=like", "mail.%"),
                ]
            )
            .mapped("name")
        )
        fields = self.env[model]._fields
        for mixin in MAIL_MIXINS:
            if mixin in self.env:  # the mail module installed
                useless |= set(self.env[mixin]._fields) & set(fields)
        return useless - {"id", "display_name"}

    @api.model
    def get_sql_query(self, model: str, domain: list = None, order: str = "") -> str:
        """Bare SELECT reading `model` straight from Postgres.

        The kpiten app streams this query with connectorx / polars and
        normalizes the result with `Df` into the parquet of the store.
        """
        return kt_sql.build_select(self.env, model, domain, order)

    @api.model
    def create_sql_view(self, model: str) -> str:
        """Create (or replace) the persistent SQL view `kpiten_<model>`.

        Used by the 'view' extraction mode. Returns the view name.
        """
        return kt_sql.create_sql_view(self.env, model)

    def _get_model_direct_fields(self, model: str) -> set:
        """
        Introspect the Odoo model to return all its direct fields
        exploitable (scalars + many2one), excluding heavy types.
        """
        model_obj = self.env[model]
        useless = self._get_useless_fields(model)
        result = set()
        for fname, field in model_obj._fields.items():
            # Exclure les champs privés Odoo (_log_access, etc.)
            if fname.startswith("_"):
                continue
            # Exclure les types non exploitables
            if field.type in EXCLUDED_FIELD_TYPES:
                continue
            if field.name in useless:
                continue
            if field.compute and not field.store:
                continue
            result.add(fname)
        return result

    @api.model
    def get_fields_metadata(self, model: str) -> dict:
        direct = self._get_model_direct_fields(model)
        fields = {}
        for field in self.env["ir.model.fields"].search([("model", "=", model)]):
            if field.name not in direct:
                continue
            fields[field.name] = {
                "type": field.ttype,
                "string": field.field_description,
                "rel": field.relation,
                "translatable": field.translate,
            }
        return fields

    def _get_relational_paths_for_model(self, model: str) -> set:
        """
        For each Many2one field in the main model, checks if the model
        target is referenced in FIELDS_MAP and constructs the dot-notation paths.

        I.E.: order_id → sale.order → if 'sale.order' in FIELDS_MAP
            → {'order_id.name', 'order_id.date_order', ...}
        """
        model_obj = self.env[model]
        paths = set()
        FIELDS_MAP = self._follow_relational_fields()

        for fname, field in model_obj._fields.items():
            if field.type != "many2one":
                continue

            comodel = field.comodel_name  # ex: 'sale.order', 'res.partner'
            if not comodel or comodel not in FIELDS_MAP:
                continue

            for sub_field in FIELDS_MAP[comodel]:
                paths.add(f"{fname}.{sub_field}")

        return paths

    @api.model
    def check_uuid(self, user_uuid):
        """The user id of a valid (issued less than a week ago) uuid, else False.

        The dashboard apps ask it to open a session : an expired uuid opens nothing.
        """
        return self.env["res.users.log"]._valid_uuid_user(user_uuid)

    @api.model
    def get_records_action(self, model: str) -> int:
        """The id of the list action that shows, in Odoo, the records a KPI lists.

        One generic action per model, made when it is first asked : its domain is
        `[('id', 'in', active_ids)]`, so a link `/odoo/action-<id>?active_ids=1,2,3`
        opens the list of those records. The domain does not widen anything : Odoo
        applies the rights and the record rules of whoever opens the link. Only the
        models of a KpiTen dataset are served.
        """
        datasets = self.env["kt.dataset"].sudo().search([]).mapped("model_id.model")
        if model not in datasets:
            raise exceptions.UserError(_("%s is not a KpiTen data source.", model))
        actions = self.env["ir.actions.act_window"].sudo()
        action = actions.search(
            [("res_model", "=", model), ("name", "=", RECORDS_ACTION_NAME)], limit=1
        )
        if not action:
            action = actions.create(
                {
                    "name": RECORDS_ACTION_NAME,
                    "res_model": model,
                    "domain": "[('id', 'in', active_ids)]",
                    "view_mode": f"{LIST},form",
                }
            )
        return action.id

    @api.model
    def can_edit_tiles(self, user_id=None):
        """Whether the user (default : the current one) is a KpiTen manager.

        The dashboard apps read Odoo with one RPC account : they ask here before
        they let a user edit the tiles (the edit mode).
        """
        user = self.env["res.users"].sudo().browse(user_id or self.env.uid)
        return user.has_group("kpiten.group_kpiten_manager")

    @api.model
    def _kpiten_session(self, application: str = "shiny") -> tuple[str, str]:
        """A session of the current user in a front : `(session, external_url)`.

        The front checks the uuid of the user (`kt.check_uuid`) and answers a session
        token ; `external_url` is the address of the front for the browser. Raises
        `UserError` when the front refuses or cannot be reached.
        """
        log = (
            self.env["res.users.log"]
            .with_user(SUPERUSER_ID)
            .search([("create_uid", "=", self.env.user.id)], order="id desc", limit=1)
        )
        if not log._uuid_is_valid():  # older than a week : issue a new one
            log._renew_uuid()
            # the app checks it in its own transaction, right below : commit first
            self.env.cr.commit()
        urls = self.env["res.company"]._get_kpiten_services(application)
        try:
            resp = requests.post(
                f"{urls['internal_url']}/",
                json={"user_uuid": log.uuid, "db": self.env.cr.dbname},
                timeout=30,
            )
            answer = resp.json()
        except Exception as err:
            raise exceptions.UserError(
                _("%s is not reachable : %s") % (application, err)
            )
        if not answer.get("session"):
            raise exceptions.UserError(answer.get("error") or "No error was specified")
        logger.info("kpiten %s session : %s", application, answer["session"])
        return answer["session"], urls["external_url"]

    @api.model
    def action_redirect_to_kpiten(self, *args, application=None):
        """Redirect to one of the dashboard apps ('shiny' or 'nicegui').

        The application is the keyword, or the last string among the positional
        arguments : an RPC call gives `args: ["nicegui"]`, or `[[], "nicegui"]`
        with the ids first, as it did when the method was not an `api.model` (a
        bare string was then read as a list of ids and Shiny opened instead).
        """
        application = application or next(
            (arg for arg in reversed(args) if isinstance(arg, str)), "shiny"
        )
        logger.info("action_redirect_to_kpiten : application=%s", application)
        try:
            session, external_url = self._kpiten_session(application)
        except exceptions.UserError as err:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": f"Failed to open KPIten ({application} app)",
                    "message": f"Here is the full error : \n{err}",
                    "type": "warning",  # 'info', 'success', 'warning', 'danger'
                    "sticky": False,  # True keeps it until manually closed
                },
            }
        route = "dashboard"
        return {
            "type": "ir.actions.act_url",
            "url": f"{external_url}/{route}/auth?session={session}",
            "target": "new",
        }


# the mixins of the chatter and of the activities : their fields are not used
MAIL_MIXINS = ("mail.thread", "mail.activity.mixin")

# Fields to systematically exclude
EXCLUDED_FIELD_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]
