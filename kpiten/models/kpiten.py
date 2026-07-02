from math import exp2

from odoo import _, api, exceptions, models


class Kpiten(models.AbstractModel):
    _name = "kpiten"
    _description = "KpiTen methods"

    def _follow_relational_fields(self):
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
            "hr.employee": {"employee_type"},
        }

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
        self, model: str, domain: list, user_id: int, limit: int = None
    ) -> list[dict]:
        """
        i.e. env['kpiten'].get_record_vals("sale.order.line", [], 2, limit=10)

        Returns a list of dicts for each model record,
        by automatically discovering all its direct fields by introspection,
        and by enriching via the relational fields defined in FIELDS_MAP.

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
        records = self.env[model].with_user(user_id).search(domain, limit=limit)
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
        resolved_roots = {path.split(".")[0] for path in relational_paths}
        # On garde le Many2one brut uniquement s'il n'est pas couvert par FIELDS_MAP
        # (utile pour avoir l'id de relation même sans sous-champs déclarés)

        return list(data_by_id.values())

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

    @api.model
    def get_translations(self, model):
        pass

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

    def resolve_field_path(self, model, ids, path):
        """
        Resolves a (possibly dotted) field path for a list of record ids of `model`.
        Returns {id: value}.

        Examples:
            resolve_field_path(env, 'mrp.workcenter.productivity', ids, 'duration')
            resolve_field_path(env, 'mrp.workcenter.productivity', ids, 'user_id.employee_id.employee_type')
        """
        field, *rest = path.split(
            ".", 1
        )  # rest is [] if no more dots, else [remaining_path]

        if not rest:
            # base case: last segment, fetch the real value
            records = self.env[model].search_read([("id", "in", ids)], ["id", field])
            return {r["id"]: r[field] for r in records}

        # recursive case: this segment is relational, hop through it
        records = self.env[model].search_read([("id", "in", ids)], ["id", field])

        # many2one comes back as (related_id, display_name) or False if empty
        id_to_related_id = {
            r["id"]: (r[field][0] if r[field] else None) for r in records
        }

        related_model = self.env[model]._fields[field].comodel_name
        related_ids = list({v for v in id_to_related_id.values() if v is not None})

        related_result = self.resolve_field_path(related_model, related_ids, rest[0])

        # stitch: base_id -> related_id -> resolved value
        return {
            base_id: related_result.get(related_id)
            for base_id, related_id in id_to_related_id.items()
        }


# Fields to systematically exclude
EXCLUDED_FIELD_TYPES = [
    "many2many",
    "one2many",
    "properties",
    "properties_definition",
    "binary",
]
