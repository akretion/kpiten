"""A small, representative sample of any Odoo model : a DataFrame or a Parquet."""

import io
from datetime import date, datetime

from odoo import _, api, models
from odoo.exceptions import UserError

# one2many / many2many would need list columns ; binary and html fields make the
# sample heavy and unpredictable
EXCLUDED_FIELD_TYPES = ("one2many", "many2many", "binary", "html")
DEFAULT_SIZE = 20
# above this many records the ids are not all listed : Postgres draws pages at random
BIG_TABLE = 200_000

STYLE_WIZARD = "wizard"  # a many2one is `x` (the id) and `x.name`
STYLE_STORE = "store"  # a many2one is `x` (the name) and `x_` (the id), dates are days


def _plain(value):
    """An ORM value as a DataFrame cell (`False` is an empty cell)."""
    return None if value is False else value


class ParquetSample(models.AbstractModel):
    _name = "parquet.sample"
    _description = "Parquet sample of a model"

    @api.model
    def sample_records(self, model, size=DEFAULT_SIZE, domain=None):
        """`size` records of `model` that the user may read, spread over its history.
        `domain` restricts them (the lines of the sampled orders, for instance)."""
        Model = self.env[model]
        domain = domain or []
        total = Model.search_count(domain)
        if not total:
            raise UserError(_("The model %s has no records to sample from.", model))
        order = (
            "create_date asc, id asc" if "create_date" in Model._fields else "id asc"
        )
        if total <= size:
            return Model.search(domain, order=order)
        if total <= BIG_TABLE:
            ids = Model.search(domain, order=order).ids
        else:
            # about 20 times more ids than needed, drawn by Postgres ; the ORM then
            # applies the record rules of the user to them
            percent = min(100.0, max(0.001, size * 20 * 100.0 / total))
            self.env.cr.execute(
                f'SELECT id FROM "{Model._table}" TABLESAMPLE SYSTEM (%s) LIMIT %s',
                (percent, size * 20),
            )
            ids = Model.search(
                domain + [("id", "in", [row[0] for row in self.env.cr.fetchall()])],
                order=order,
            ).ids
        if len(ids) <= size:
            return Model.browse(ids)
        step = len(ids) / float(size)  # evenly spaced along the history
        return Model.browse([ids[int(i * step)] for i in range(size)])

    @api.model
    def sample_with_meta(
        self, model, size=DEFAULT_SIZE, style=STYLE_WIZARD, extra_paths=(), domain=None
    ):
        """The sample as `(polars DataFrame, {column: {"type": odoo type}})`.

        `extra_paths` are dotted paths followed from each record
        (`partner_id.country_id.name`), added as columns. `domain` restricts the records.
        """
        try:
            import polars as pl
        except ImportError:
            raise UserError(
                _("The 'polars' Python package is required : pip install polars")
            )
        Model = self.env[model]
        fields_info = Model.fields_get()
        # the stored fields, like the KpiTen store : a computed field that is not stored
        # is slow and may need more access than the user has
        export_fields = [
            name
            for name, info in fields_info.items()
            if info.get("type") not in EXCLUDED_FIELD_TYPES
            and Model._fields[name].store
        ]
        store = style == STYLE_STORE

        def cell(value):
            value = _plain(value)
            if store and isinstance(value, datetime):
                return value.date()  # the store keeps the day
            return value

        meta, rows = {}, []
        for rec in self.sample_records(model, size, domain):
            row = {}
            for name in export_fields:
                ftype = fields_info[name].get("type")
                value = rec[name]
                if ftype == "many2one" and store:
                    row[name] = value.display_name if value else None
                    row[f"{name}_"] = value.id if value else None
                    meta[name], meta[f"{name}_"] = {"type": "char"}, {"type": "integer"}
                elif ftype == "many2one":
                    row[name] = value.id if value else None
                    row[f"{name}.name"] = value.display_name if value else None
                    meta[name], meta[f"{name}.name"] = {"type": "many2one_id"}, {
                        "type": "char"
                    }
                elif ftype == "boolean":
                    row[name] = bool(value)
                    meta[name] = {"type": ftype}
                else:
                    row[name] = cell(value)
                    meta[name] = {"type": ftype}
            for path in extra_paths:
                values = rec.mapped(path)
                first = values[0] if values else None
                row[path] = cell(getattr(first, "display_name", first))
                meta[path] = {"type": "path"}
            rows.append(row)
        try:
            frame = pl.DataFrame(rows, infer_schema_length=None)
        except Exception as exc:
            raise UserError(_("Could not build the sample DataFrame: %s", exc))
        if store:  # a column of dates only, as the store has it
            date_columns = [
                c
                for c in frame.columns
                if frame.schema[c] == pl.Datetime or frame.schema[c] == pl.Date
            ]
            frame = frame.with_columns([pl.col(c).cast(pl.Date) for c in date_columns])
        return frame, meta

    @api.model
    def sample_dataframe(self, model, size=DEFAULT_SIZE, **kwargs):
        """The sample as a polars DataFrame (see `sample_with_meta`)."""
        return self.sample_with_meta(model, size, **kwargs)[0]

    @api.model
    def sample_parquet(self, model, size=DEFAULT_SIZE, **kwargs):
        """The sample as a Parquet file : `(filename, bytes)`."""
        frame = self.sample_dataframe(model, size, **kwargs)
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        return "%s_sample.parquet" % model.replace(".", "_"), buffer.getvalue()
