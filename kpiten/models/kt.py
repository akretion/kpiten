import logging

import requests

from odoo import SUPERUSER_ID, api, exceptions, models

logger = logging.getLogger(__name__)


class Kt(models.AbstractModel):
    _name = "kt"
    _description = "Kt methods"

    def _follow_relational_fields(self):
        """
        for walkable paths only (e.g : some_model.user_id.name)
        [destined to be consumed by odoo's mapped function]
        """
        return {
            "product.product": {
                "default_code",
                "name",
                "categ_id.name",
                "product_tmpl_id.type",
            },
            "product.category": {"name"},
            "res.partner": {"commercial_partner_id.name", "commercial_partner_id.ref"},
            "res.users": {"name"},
        }

    def _get_reverse_lookups(self):
        """TODO is it required ?

        May contains a such dict
            {
            "mrp.workcenter.productivity": {
                "user_id": {
                    "target_model": "hr.employee",
                    "target_link_field": "user_id",
                    "target_value_field": "employee_type",
                },
            }
        """
        return {}

    def _rename_fields(self):
        """Used by other modules to rename ... fields !
            {
                "model1": {
                    "field1": new_name1,
                }
            }
        if keys aren't exist it doesn't break your instance.
        """
        return {}

    @api.model
    def kpi_rec_name(self, model):
        # Allow to expose _rec_name to rpc
        return self.env[model]._rec_name

    @api.model
    def get_allowed_fields(self, model: str, allowed_uid: int) -> list[str]:
        stored_fields = (
            self.env["ir.model.fields"]
            .search([("model", "=", model), ("store", "=", True)])
            .mapped("name")
        )
        user_fields = self.env[model].with_user(allowed_uid)._fields

        additionnal_fields = self._get_relational_paths_for_model(model)

        return [
            *[field for field in user_fields if field in stored_fields],
            *additionnal_fields,
        ]

    def _get_useless_fields(self):
        """return Dict of list
         - keys are models
         - list element are fields

        to get a raw list of fields:
            ",".join(env["ir.model.fields"].search([
            ("stored", "=", True),
            ("name", "not like", "%_ids"),
            ("ttype", "not in", ("many2many", "one2many", "properties", "properties_definition", "binary")),
            ("model", "=", "sale.order")]).mapped("name"))
        """
        return {}

    @api.model
    def get_record_vals(
        self,
        model: str,
        domain: list,
        user_id: int,
        limit: int = None,
        offset: int = 0,
        order: str = "",
    ) -> list[dict]:
        """
        i.e. env['kt'].get_record_vals("sale.order.line", [], 2, limit=10, offset=10)

        Returns a list of dicts for each model record,
        by automatically discovering all its direct fields by introspection,
        and by enriching via the relational fields defined in FIELDS_MAP.

        `limit` / `offset` allow paginated extraction of huge tables so the
        RPC call never fetches the whole table in one shot.

        `order` is an optional Odoo search ordering string (e.g.
        "create_date desc, id desc") used to paginate from the most recent to
        the oldest records.

        :param user_id:  ID de l'utilisateur pour le contrôle d'accès
        :return:         Liste de dicts avec toutes les valeurs résolues
        """
        # 1. Découverte automatique des champs directs du modèle
        direct_fields = self._get_model_direct_fields(model)
        direct_fields.add("id")  # toujours inclus

        # 2. Construction des paths relationnels depuis FIELDS_MAP
        relational_paths = self._get_relational_paths_for_model(model)

        # Les champs racine Many2one nécessaires pour mapped()
        # sont déjà dans direct_fields (détectés comme many2one)

        # 3. Recherche des enregistrements
        records = (
            self.env[model]
            .with_user(user_id)
            .search(domain, limit=limit, offset=offset, order=order)
        )
        if not records:
            return []

        # def hardcoded_filter(c: str):
        #     if c != "hours_today":
        #         return True
        #     else:
        #         print(f"excluded : {c}")

        # direct_fields = filter(hardcoded_filter, direct_fields)

        # 4. Lecture des champs directs en une seule requête
        raw_data = records.read(list(direct_fields))

        def replace_null(val):
            # replace False by None because dataframe require None
            if not val:
                return None
            return val

        data_by_id = {
            row["id"]: dict({k: replace_null(v) for k, v in row.items()})
            for row in raw_data
        }

        # 5. Résolution des paths dot-notation via mapped()
        for path in relational_paths:
            root_field, sub_path = path.split(".", 1)
            for record in records:
                row = data_by_id[record.id]
                related = getattr(record, root_field, None)
                if not related:
                    row[path] = False
                    continue
                try:
                    values = related.mapped(sub_path)
                    if isinstance(values, list):
                        row[path] = values[0] if len(values) == 1 else values
                    else:
                        # recordset (Many2one imbriqué) → valeur scalaire
                        row[path] = values[0] if len(values) == 1 else list(values)
                except Exception:
                    row[path] = False

        # 6. Remplacer les Many2one bruts (id, name) par juste l'id
        #    pour les champs dont on a déjà la valeur via dot-notation
        # resolved_roots = {path.split(".")[0] for path in relational_paths}
        # On garde le Many2one brut uniquement s'il n'est pas couvert par FIELDS_MAP
        # (utile pour avoir l'id de relation même sans sous-champs déclarés)

        REVERSE_LOOKUPS = self._get_reverse_lookups()
        for root_field, lookup in REVERSE_LOOKUPS.get(model, {}).items():
            data_by_id = self._resolve_reverse_lookup(
                data_by_id,
                root_field=root_field,
                target_model=lookup["target_model"],
                target_link_field=lookup["target_link_field"],
                target_value_field=lookup["target_value_field"],
                result_key=f"{root_field}.{lookup['target_value_field']}",
            )

        return list(data_by_id.values())

    @api.model
    def get_max_create_date(self, model: str, user_id: int):
        """Most recent create_date of a model, or False if the table is empty.

        Used as the frozen upper bound for a recent->oldest paginated extract,
        so concurrent writes during the load don't shift the offsets.
        """
        record = (
            self.env[model]
            .with_user(user_id)
            .search([], order="create_date desc", limit=1)
        )
        if not record:
            return False
        return record.create_date or False

    def _get_model_direct_fields(self, model: str) -> set:
        """
        Introspect the Odoo model to return all its direct fields
        exploitable (scalars + many2one), excluding heavy types.
        """
        model_obj = self.env[model]
        result = set()
        for fname, field in model_obj._fields.items():
            # Exclure les champs privés Odoo (_log_access, etc.)
            if fname.startswith("_"):
                continue
            # Exclure les types non exploitables
            if field.type in EXCLUDED_FIELD_TYPES:
                continue
            if field.name in self._get_useless_fields():
                continue
            if field.compute and not field.store:
                continue
            result.add(fname)
        return result

    @api.model
    def get_fields_metadata(self, model: str) -> dict:
        model_obj = self.env[model]
        fields = {}
        for field in self.env["ir.model.fields"].search([("model", "=", model)]):
            if field.name not in self._get_model_direct_fields(model):
                continue
            fields[field.name] = {
                "type": field.ttype,
                "string": field.field_description,
                "rel": field.relation,
                "translatable": field.translate,
            }
        return fields

    def _get_translations(self, model, records, raw_data):
        # 4.5 Traduction
        translatable = self.env["ir.model.fields"].search(
            [("model", "=", model), ("translate", "=", True)]
        )
        model_has_translate_fields = len(translatable) > 0
        if model_has_translate_fields:
            rec_by_id = {r["id"]: r for r in raw_data}
            for record in records:
                for field in translatable:
                    translations, _ = record.get_field_translations(field.name)
                    if len(translations) > 0:
                        rec_by_id[record.id][field.name] = {
                            t["lang"]: t["value"] for t in translations
                        }

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

    def _resolve_reverse_lookup(
        self,
        data_by_id,
        root_field,
        target_model,
        target_link_field,
        target_value_field,
        result_key,
    ):
        root_ids = {
            (v[0] if isinstance(v, (list, tuple)) else v)
            for v in (row.get(root_field) for row in data_by_id.values())
            if v
        }

        matches = self.env[target_model].search_read(
            [(target_link_field, "in", list(root_ids))],
            [target_link_field, target_value_field],
        )
        value_by_root_id = {
            (
                m[target_link_field][0]
                if isinstance(m[target_link_field], (list, tuple))
                else m[target_link_field]
            ): m[target_value_field]
            for m in matches
        }

        for row in data_by_id.values():
            raw = row.get(root_field)
            raw_id = raw[0] if isinstance(raw, (list, tuple)) else raw
            if raw_id:
                row[result_key] = [raw_id, value_by_root_id.get(raw_id)]

        return data_by_id

    def action_redirect_to_kpiten(self, application: str = "shiny"):
        """Redirect to one of the dashboard apps ('shiny' or 'nicegui')."""
        logger.info("action_redirect_to_kpiten : application=%s", application)
        uuid = (
            self.env["res.users.log"]
            .with_user(SUPERUSER_ID)
            .search([("create_uid", "=", self.env.user.id)])[0]
            .uuid
        )
        urls = self.env["res.company"]._get_kpiten_services(application)
        route = "build" if application == "marimo" else "dashboard"
        try:
            resp = requests.post(
                f"{urls["internal_url"]}/",
                json={"user_uuid": uuid, "db": self.env.cr.dbname},
            )
        except Exception as err:
            raise exceptions.ValidationError(err)
        if not resp.json().get("session"):
            error = resp.json().get("error") or "No error was specified"
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": f"Failed to open KPIten ({application} app)",
                    "message": f"Here is the full error : \n{error}",
                    "type": "warning",  # 'info', 'success', 'warning', 'danger'
                    "sticky": False,  # True keeps it until manually closed
                },
            }
        session = resp.json()["session"]
        logger.info("kpiten %s session : %s", application, session)
        resp.raise_for_status()
        return {
            "type": "ir.actions.act_url",
            "url": f"{urls["external_url"]}/{route}/auth?session={session}",
            "target": "new",
        }


# Fields to systematically exclude
EXCLUDED_FIELD_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]
