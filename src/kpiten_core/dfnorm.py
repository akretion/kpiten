"""Dataframe normalization after extraction from Odoo.

Port of marimo-kpiten `services/dataframe_util.py`, without marimo:
- string datetimes -> Date columns (times truncated to the month)
- many2one `[id, name]` pairs split into `col` (name) + `col_id_` (id)
- decimal scale normalization
"""

import logging
import re
from typing import Any

import polars as pl

from kpiten_core import env

logger = logging.getLogger(__name__)


class Df:
    def __init__(
        self,
        df: pl.DataFrame,
        fields: dict[str, Any] | None = None,
        decimal_truncate: int | None = None,
    ):
        self.df = df
        self.fields = fields
        self.decimal_truncate = decimal_truncate

    def get_df(self) -> pl.DataFrame:
        self.set_datetime_string2date_columns()
        self._truncate_dates()
        self.split_many2one_result()
        if self.decimal_truncate:
            self.df = self.df.with_columns(
                pl.col(pl.Decimal).round(self.decimal_truncate)
            )
        # Normalize decimal
        self.df = self.df.with_columns(
            self.normalize_decimal_col(self.df, col).alias(col)
            for col in self.get_decimal_columns()
        )
        self._fix_false_strings()
        return self.df

    def _fix_false_strings(self):
        self.df = self.df.with_columns(pl.col(pl.String).replace("false", ""))

    def _truncate_dates(self):
        """Truncate date/datetime columns to the month as Date.

        create_date and write_date are left untouched.
        """
        excluded = {"create_date", "write_date"}
        date_cols = [
            c
            for c, dtype in zip(self.df.columns, self.df.dtypes)
            if dtype in (pl.Date, pl.Datetime) and c not in excluded
        ]
        if not date_cols:
            return
        self.df = self.df.with_columns(
            pl.col(c).cast(pl.Datetime).dt.truncate("1mo").cast(pl.Date)
            for c in date_cols
        )

    def get_decimal_columns(self) -> list[str]:
        return [
            name
            for name, dtype in zip(self.df.columns, self.df.dtypes)
            if isinstance(dtype, pl.Decimal)
        ]

    def normalize_decimal_col(self, df: pl.DataFrame, col_name: str) -> pl.Expr:
        """Reduce the scale of a Decimal column to its column max significant places."""
        series = df[col_name]
        if series.null_count() == series.len() or series.len() == 0:
            # all-null / empty Decimal column : nothing to normalize
            return pl.col(col_name)
        as_str = series.cast(pl.String)
        decimal_parts = as_str.str.extract(r"\.(\d+)$", 1)
        significant = decimal_parts.map_elements(
            lambda s: len(s.rstrip("0")) if s else 0, return_dtype=pl.Int32
        )
        max_scale = significant.max()
        if max_scale is None:
            return pl.col(col_name)
        return pl.col(col_name).cast(pl.Decimal(scale=max_scale))

    def set_datetime_string2date_columns(self):
        fields = {k: v for k, v in (self.fields or {}).items() if isinstance(v, dict)}
        datetime_fields = [
            x
            for x in fields
            if x in self.df.columns
            and (
                fields[x].get("type") == "datetime"
                or "date" in x
                and not self.df[x].is_null().all()
            )
        ]
        self.df = self.df.with_columns(
            pl.col(datetime_fields).cast(pl.String).str.to_datetime(strict=False)
        )
        self.df = self.df.with_columns(pl.col(datetime_fields).cast(pl.Date))

    def split_many2one_result(self):
        """Convert Many2one list fields to 2 columns.

        i.e. company_id [2, "My Company"] ->
            company_id: "My Company"
            company_id_: 2
        """
        for col in self.df.columns:
            if not re.search(r"_(u?id)", col):
                continue
            id_col = re.sub(r"_(u?id)", "_id_", col)
            is_m2o = col in self._m2o_fields()
            if self.df[col].dtype == pl.List:
                if is_m2o or not self.df[col].is_null().all():
                    self.df = self.df.with_columns(
                        pl.col(col).list.get(0).cast(pl.Int64).alias(id_col),
                        pl.col(col).list.get(1).str.strip_chars().alias(col),
                    )
            elif is_m2o:
                # all-null m2o column (Null dtype) : emit null id column so
                # the schema matches the full extract
                self.df = self.df.with_columns(
                    pl.lit(None, dtype=pl.Int64).alias(id_col)
                )

    def _m2o_fields(self) -> set[str]:
        return {
            name
            for name, spec in (self.fields or {}).items()
            if isinstance(spec, dict) and spec.get("type") == "many2one"
        }

    @classmethod
    def from_raw(
        cls,
        table: str,
        raw_vals: list[dict],
        metadata: dict | None = None,
        decimal_truncate: int | None = None,
    ) -> "Df":
        """Build the Df helper from raw record vals (see Backend.get_record_vals)."""
        df = pl.DataFrame(raw_vals, strict=False, infer_schema_length=None)
        return cls(
            df,
            fields=metadata,
            decimal_truncate=decimal_truncate or env.decimal_truncate,
        )
