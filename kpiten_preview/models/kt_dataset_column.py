from odoo import _, api, fields, models

from odoo.addons.kpiten.compat import LIST

SAMPLE_SIZE = 200
EXAMPLES = 3
DATE_PARTS = ("year", "quarter", "month", "week", "day")


class KtDataset(models.Model):
    _inherit = "kt.dataset"

    def action_view_columns(self):
        """The columns of the dataset, as a tile sees them, in a list."""
        self.ensure_one()
        Column = self.env["kt.dataset.column"]
        Column.search([("dataset_id", "=", self.id)]).unlink()
        Column.create(self._column_values())
        return {
            "type": "ir.actions.act_window",
            "name": _("Columns of %s") % self.display_name,
            "res_model": "kt.dataset.column",
            "view_mode": LIST,
            "domain": [("dataset_id", "=", self.id)],
        }

    def _column_values(self):
        """One dict per column : the fields and the id of each many2one, the relational
        paths declared for the dataset, and the parts of each date."""
        import polars as pl

        model = self.model_id.model
        kt = self.env["kt"]
        frame, meta = self.env["parquet.sample"].sample_with_meta(
            model,
            SAMPLE_SIZE,
            style="store",
            extra_paths=sorted(kt._get_relational_paths_for_model(model)),
        )
        many2one = {
            c[:-1] for c in frame.columns if c.endswith("_") and c[:-1] in frame.columns
        }

        def examples(series):
            values = series.drop_nulls().unique(maintain_order=True).head(EXAMPLES)
            return ", ".join(str(v)[:40] for v in values.to_list())

        rows = []
        for name in frame.columns:
            if name.endswith("_") and name[:-1] in many2one:
                origin = "Id of a many2one"
            elif meta.get(name, {}).get("type") == "path":
                origin = "Relational path"
            else:
                origin = "Field"
            rows.append(
                {
                    "dataset_id": self.id,
                    "name": name,
                    "dtype": str(frame.schema[name]),
                    "origin": origin,
                    "examples": examples(frame[name]),
                }
            )
            if frame.schema[name] == pl.Date:
                for part in DATE_PARTS:
                    values = getattr(pl.col(name).dt, part)()
                    rows.append(
                        {
                            "dataset_id": self.id,
                            "name": f"{name}.{part}",
                            "dtype": "Int32",
                            "origin": "Date part",
                            "examples": examples(frame.select(values.alias("v"))["v"]),
                        }
                    )
        return rows


class KtDatasetColumn(models.TransientModel):
    _name = "kt.dataset.column"
    _description = "A column of a KpiTen dataset"
    _order = "name"

    dataset_id = fields.Many2one("kt.dataset", required=True, ondelete="cascade")
    name = fields.Char(help='The name to use in a tile : pl.col("name").')
    dtype = fields.Char(string="Type", help="The polars type in the store.")
    origin = fields.Selection(
        [
            ("Field", "Field"),
            ("Id of a many2one", "Id of a many2one"),
            ("Relational path", "Relational path"),
            ("Date part", "Date part"),
        ],
        help="A many2one gives its name in `x` and its id in `x_`.",
    )
    examples = fields.Char(help="A few values of the sample.")
