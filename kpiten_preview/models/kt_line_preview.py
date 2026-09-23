from odoo import _, api, fields, models

from odoo.addons.kpiten.compat import get_param

DEFAULT_SIZE = 200


class KtDatasetLinePreview(models.TransientModel):
    _name = "kt.dataset.line.preview"
    _description = "Preview of a KpiTen tile"

    line_id = fields.Many2one("kt.dataset.line", required=True, ondelete="cascade")
    size = fields.Integer(
        default=DEFAULT_SIZE,
        help="Records of the dataset the tile is computed on (a sample, spread over "
        "its history, of what the user may read).",
    )
    preview_html = fields.Html(readonly=True, sanitize=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.action_refresh()
        return records

    def action_refresh(self):
        """Compute the tile on a new sample and draw it."""
        for wizard in self:
            wizard.preview_html = wizard._compute_html()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _needed_models(self, line, model):
        """The models whose sample the tile needs : its dataset, and those a graph,
        pivot or union reads (`from`, `union_model`, `mapping`)."""
        from kpiten_core import serial

        needed = {model}
        if line.kind != "data" and line.definition:
            try:
                definition = serial.loads(line.definition)
            except Exception:
                return needed
            needed |= {
                m for m in (definition.get("from"), definition.get("union_model")) if m
            }
            needed |= set(definition.get("mapping") or {})
        return needed

    def _compute_html(self):
        from kpiten_core import env as core_env
        from kpiten_core import links, tiles
        from kpiten_core.tiles import TileError

        render = self.env["kt.preview.render"]
        line = self.line_id
        model = line.dataset_id.model_id.model
        if not model:
            return render.error_html(_("The tile has no dataset."))
        kt = self.env["kt"]
        sampler = self.env["parquet.sample"]
        try:
            store = {}
            for name in sorted(self._needed_models(line, model)):
                paths = sorted(kt._get_relational_paths_for_model(name))
                store[name] = sampler.sample_dataframe(
                    name, self.size or DEFAULT_SIZE, style="store", extra_paths=paths
                ).lazy()
            tiles.set_chart_config(self.env["kt.config"].get_config_json())
            links.set_odoo_url(get_param(self.env, "web.base.url"))
            with core_env.db_scope(self.env.cr.dbname):
                result = tiles.exec_tile(
                    {
                        "id": line.id,
                        "name": line.name,
                        "kind": line.kind,
                        "content": line.definition,
                        "drill": line.drill_definition or None,
                    },
                    model,
                    store,
                    [],
                )
        except TileError as err:
            return render.error_html(str(err))
        except Exception as err:  # a bad sample or definition must not break the form
            return render.error_html(f"{type(err).__name__} : {err}")
        return render.result_html(line, result)
