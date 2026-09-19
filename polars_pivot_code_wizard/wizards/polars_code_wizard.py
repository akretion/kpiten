# -*- coding: utf-8 -*-
import base64
import html as html_lib
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SAMPLE_SIZE = 20


class PolarsPivotCodeWizard(models.TransientModel):
    _name = "polars.pivot.code.wizard"
    _description = "Polars Pivot Code Generator"

    # ------------------------------------------------------------------
    # Data source
    # ------------------------------------------------------------------
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        help="Odoo model to sample data from and build the pivot for.",
    )
    model_name = fields.Char(related="model_id.model", string="Technical Model Name")

    sample_file = fields.Binary(string="Sample Parquet File", readonly=True)
    sample_filename = fields.Char(string="Sample Filename", readonly=True)

    # Columns found in the extracted Parquet sample; they back the
    # Index/Column/Value dropdowns below through a classic Many2one.
    column_ids = fields.One2many(
        "polars.pivot.column",
        "wizard_id",
        string="Available Columns",
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Pivot parameters — dropdowns are filled with the columns actually
    # found in the extracted Parquet sample.
    # ------------------------------------------------------------------
    index_field = fields.Many2one(
        "polars.pivot.column",
        string="Index Field (rows)",
    )
    column_field = fields.Many2one(
        "polars.pivot.column",
        string="Column Field (on)",
    )
    value_field = fields.Many2one(
        "polars.pivot.column",
        string="Value Field (values)",
        help="Leave empty to just count rows (aggregate_function='len').",
    )

    aggregate_function = fields.Selection(
        [
            ("len", "Count"),
            ("sum", "Sum"),
            ("mean", "Mean"),
            ("min", "Minimum"),
            ("max", "Maximum"),
            ("first", "First Value"),
            ("median", "Median"),
        ],
        string="Aggregate Function",
        default="len",
        required=True,
    )

    # ------------------------------------------------------------------
    # Date handling
    # ------------------------------------------------------------------
    has_date = fields.Boolean(string="One Axis Is a Date")
    date_axis = fields.Selection(
        [("index", "Index (rows)"), ("column", "Column (on)")],
        string="Date Axis",
    )
    date_granularity = fields.Selection(
        [
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("quarter", "Quarter"),
            ("year", "Year"),
        ],
        string="Granularity",
        default="month",
    )

    # ------------------------------------------------------------------
    # Finishing options
    # ------------------------------------------------------------------
    fill_null = fields.Boolean(string="Fill Missing Values", default=True)
    fill_null_value = fields.Char(string="Fill Value", default="0")
    sort_result = fields.Boolean(string="Sort Result by Index", default=True)
    df_var = fields.Char(string="DataFrame Variable Name", default="df", required=True)

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------
    generated_code = fields.Text(string="Generated Polars Code (raw)", readonly=True)
    code_preview = fields.Html(
        string="Polars Code Preview", readonly=True, sanitize=False
    )

    pivot_html = fields.Text(string="Generated Pivot Table (HTML, raw)", readonly=True)
    pivot_preview = fields.Html(
        string="Pivot Table Preview", readonly=True, sanitize=False
    )

    # ==================================================================
    # Onchange
    # ==================================================================
    @api.onchange("model_id")
    def _onchange_model_id(self):
        self.sample_file = False
        self.sample_filename = False
        self.column_ids = [(5, 0, 0)]
        self.index_field = False
        self.column_field = False
        self.value_field = False
        self.generated_code = False
        self.code_preview = False
        self.pivot_html = False
        self.pivot_preview = False

    @api.onchange("aggregate_function")
    def _onchange_aggregate_function(self):
        if self.aggregate_function == "len":
            self.value_field = False

    @api.onchange("index_field", "column_field")
    def _onchange_detect_date_axis(self):
        """Convenience: auto-detect and pre-fill the date axis when one of
        the selected columns is a Date/Datetime field."""
        col_type = self.column_field.type if self.column_field else None
        idx_type = self.index_field.type if self.index_field else None

        if col_type in ("date", "datetime"):
            self.has_date = True
            self.date_axis = "column"
        elif idx_type in ("date", "datetime"):
            self.has_date = True
            self.date_axis = "index"
        else:
            self.has_date = False
            self.date_axis = False

    @api.onchange("has_date")
    def _onchange_has_date(self):
        if not self.has_date:
            self.date_axis = False

    # ==================================================================
    # Column helpers
    # ==================================================================
    @staticmethod
    def _col_name(field):
        """Return the Parquet column name for a Many2one column field."""
        return field.name if field else ""

    # ==================================================================
    # Step 1: extract a heterogeneous sample of the model into Parquet
    # ==================================================================
    def action_extract_sample(self):
        self.ensure_one()
        if not self.model_id:
            raise UserError(_("Please select a model first."))

        try:
            import polars as pl
        except ImportError:
            raise UserError(
                _(
                    "The 'polars' Python package is required on the Odoo "
                    "server to extract sample data. Install it with: "
                    "pip install polars"
                )
            )

        # the sampling itself lives in the parquet_sample module
        df, columns_meta = self.env["parquet.sample"].sample_with_meta(
            self.model_name, SAMPLE_SIZE
        )

        buffer = io.BytesIO()
        df.write_parquet(buffer)
        filename = "%s_sample.parquet" % self.model_name.replace(".", "_")

        self.write(
            {
                "sample_file": base64.b64encode(buffer.getvalue()),
                "sample_filename": filename,
                "column_ids": [
                    (5, 0, 0),
                ]
                + [
                    (0, 0, {"name": name, "type": columns_meta[name].get("type")})
                    for name in df.columns
                ],
                "index_field": False,
                "column_field": False,
                "value_field": False,
                "generated_code": False,
                "code_preview": False,
                "pivot_html": False,
                "pivot_preview": False,
            }
        )

        return self._reopen()

    # ==================================================================
    # Step 2: generate the Polars code AND actually run it on the sample
    # ==================================================================
    def action_generate_code(self):
        self.ensure_one()

        if not self.index_field or not self.column_field:
            raise UserError(_("Please select an Index Field and a Column Field."))
        if self.aggregate_function != "len" and not self.value_field:
            raise UserError(
                _(
                    "Please select a Value Field for this aggregate function "
                    "(only 'Count' can work without one)."
                )
            )
        if not self.sample_file:
            raise UserError(_("Please extract sample data first."))

        try:
            import polars as pl
        except ImportError:
            raise UserError(
                _(
                    "The 'polars' Python package is required on the Odoo "
                    "server. Install it with: pip install polars"
                )
            )

        date_field = None
        if self.has_date and self.date_axis:
            date_field = self._col_name(
                self.index_field if self.date_axis == "index" else self.column_field
            )

        index_expr = (
            "period"
            if date_field and self.date_axis == "index"
            else self._col_name(self.index_field)
        )
        column_expr = (
            "period"
            if date_field and self.date_axis == "column"
            else self._col_name(self.column_field)
        )
        if self.aggregate_function == "len":
            values_expr = self._col_name(self.value_field) or self._col_name(
                self.index_field
            )
        else:
            values_expr = self._col_name(self.value_field)

        # ---- Build the readable code snippet ----
        code_lines = self._build_code_lines(
            date_field, index_expr, column_expr, values_expr
        )
        generated_code = "\n".join(code_lines)

        # ---- Actually run the equivalent pivot on the sample data ----
        try:
            df = pl.read_parquet(io.BytesIO(base64.b64decode(self.sample_file)))
            result_df = self._run_pivot(
                pl, df, date_field, index_expr, column_expr, values_expr
            )
            pivot_html = self._dataframe_to_html(result_df)
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_("Error while computing the pivot: %s") % exc)

        self.write(
            {
                "generated_code": generated_code,
                "code_preview": self._as_code_block(generated_code),
                "pivot_html": pivot_html,
                "pivot_preview": pivot_html,
            }
        )

        return self._reopen()

    # ==================================================================
    # Code generation (text only, mirrors _run_pivot exactly)
    # ==================================================================
    def _build_code_lines(self, date_field, index_expr, column_expr, values_expr):
        lines = ["import polars as pl", ""]
        filename = self.sample_filename or "sample.parquet"
        lines.append("%s = pl.read_parquet('%s')" % (self.df_var, filename))
        lines.append("")

        bucket_lines = []
        if date_field:
            if self.date_granularity == "week":
                bucket_lines.append(
                    "    .with_columns(pl.col('%s').dt.truncate('1w').alias('period'))"
                    % date_field
                )
            elif self.date_granularity == "quarter":
                bucket_lines.append("    .with_columns(")
                bucket_lines.append(
                    "        (pl.col('%s').dt.year().cast(pl.Utf8) + '-Q' "
                    "+ pl.col('%s').dt.quarter().cast(pl.Utf8)).alias('period')"
                    % (date_field, date_field)
                )
                bucket_lines.append("    )")
            else:
                fmt_map = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
                fmt = fmt_map.get(self.date_granularity, "%Y-%m")
                bucket_lines.append(
                    "    .with_columns(pl.col('%s').dt.strftime('%s').alias('period'))"
                    % (date_field, fmt)
                )

        lines.append("pivot = (")
        lines.append("    %s" % self.df_var)
        lines.extend(bucket_lines)
        lines.append("    .pivot(")
        lines.append("        values='%s'," % values_expr)
        lines.append("        index='%s'," % index_expr)
        lines.append("        on='%s'," % column_expr)
        lines.append("        aggregate_function='%s'," % self.aggregate_function)
        lines.append("    )")

        if self.fill_null:
            fill_repr = self._fill_value_repr()
            lines.append("    .fill_null(%s)" % fill_repr)

        if self.sort_result:
            lines.append("    .sort('%s')" % index_expr)

        lines.append(")")
        lines.append("")

        if date_field and self.date_axis == "column":
            lines.append("# pivot() does not sort columns automatically:")
            lines.append("# force a chronological column order explicitly.")
            lines.append("sorted_columns = ['%s'] + sorted(" % index_expr)
            lines.append("    c for c in pivot.columns if c != '%s'" % index_expr)
            lines.append(")")
            lines.append("pivot = pivot.select(sorted_columns)")
            lines.append("")

        lines.append("print(pivot)")
        return lines

    def _fill_value_repr(self):
        raw_val = self.fill_null_value or "0"
        try:
            float(raw_val)
            return raw_val
        except ValueError:
            return "'%s'" % raw_val

    # ==================================================================
    # Real execution (mirrors _build_code_lines exactly)
    # ==================================================================
    def _run_pivot(self, pl, df, date_field, index_expr, column_expr, values_expr):
        result = df

        if date_field:
            if self.date_granularity == "week":
                result = result.with_columns(
                    pl.col(date_field).dt.truncate("1w").alias("period")
                )
            elif self.date_granularity == "quarter":
                result = result.with_columns(
                    (
                        pl.col(date_field).dt.year().cast(pl.Utf8)
                        + "-Q"
                        + pl.col(date_field).dt.quarter().cast(pl.Utf8)
                    ).alias("period")
                )
            else:
                fmt_map = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
                fmt = fmt_map.get(self.date_granularity, "%Y-%m")
                result = result.with_columns(
                    pl.col(date_field).dt.strftime(fmt).alias("period")
                )

        result = result.pivot(
            values=values_expr,
            index=index_expr,
            on=column_expr,
            aggregate_function=self.aggregate_function,
        )

        if self.fill_null:
            raw_val = self.fill_null_value or "0"
            try:
                fill_val = float(raw_val)
                if fill_val.is_integer():
                    fill_val = int(fill_val)
            except ValueError:
                fill_val = raw_val
            result = result.fill_null(fill_val)

        if self.sort_result:
            result = result.sort(index_expr)

        if date_field and self.date_axis == "column":
            sorted_columns = [index_expr] + sorted(
                c for c in result.columns if c != index_expr
            )
            result = result.select(sorted_columns)

        return result

    # ==================================================================
    # Rendering helpers
    # ==================================================================
    def _dataframe_to_html(self, df, max_rows=50):
        header = "".join("<th>%s</th>" % html_lib.escape(str(c)) for c in df.columns)
        body = []
        for i, row in enumerate(df.iter_rows()):
            if i >= max_rows:
                body.append("<tr><td colspan='%d'>...</td></tr>" % len(df.columns))
                break
            cells = "".join(
                "<td>%s</td>" % ("" if v is None else html_lib.escape(str(v)))
                for v in row
            )
            body.append("<tr>%s</tr>" % cells)
        return (
            '<table border="1" cellspacing="0" cellpadding="4" '
            'style="border-collapse:collapse;font-size:12px;">'
            "<thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
            % (header, "".join(body))
        )

    def _as_code_block(self, text):
        escaped = html_lib.escape(text or "")
        return (
            '<pre style="background:#f6f8fa;padding:12px;border-radius:6px;'
            'overflow:auto;white-space:pre-wrap;"><code>%s</code></pre>' % escaped
        )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
