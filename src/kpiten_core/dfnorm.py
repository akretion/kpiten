"""Dataframe normalization after extraction from Odoo.

Port of marimo-kpiten `services/dataframe_util.py`, without marimo:
- string datetimes -> Date columns (the time is dropped, the day is kept :
  day level kpis like « late » or « last 7 days » need it ; group by month
  with the `monthly` option of a tile instead)
- many2one `[id, name]` pairs split into `col` (name) + `col_` (id)
- decimal scale normalization
- the amounts of an order in a foreign currency in the currency of the company (see
  `to_company_currency`)
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
        self.to_company_currency()
        self.strip_name_suffix()
        return self.df

    # the rate of the currency of the row for one unit of the company currency : on an
    # order (`currency_rate`), or reached from its lines (`order_id.currency_rate`)
    RATE_COLUMNS = ("currency_rate", "order_id.currency_rate")

    def to_company_currency(self):
        """The amounts (monetary fields) of a row in a foreign currency, in the currency
        of the company : divided by the rate of the order, as Odoo's reports do. A KPI
        adds up euros, not euros and dollars. The amount in the currency of the order
        stays in `<field>_in_currency`."""
        rate = next((c for c in self.RATE_COLUMNS if c in self.df.columns), None)
        if rate is None or not self.fields:
            return
        monetary = [
            name
            for name, spec in self.fields.items()
            if isinstance(spec, dict)
            and spec.get("type") == "monetary"
            and name in self.df.columns
        ]
        if not monetary:
            return
        divisor = pl.col(rate).cast(pl.Float64)
        usable = divisor.is_not_null() & (divisor != 0)
        self.df = self.df.with_columns(
            [pl.col(name).alias(f"{name}_in_currency") for name in monetary]
            + [
                pl.when(usable)
                .then((pl.col(name).cast(pl.Float64) / divisor).round(2))
                .otherwise(pl.col(name).cast(pl.Float64))
                .alias(name)
                for name in monetary
            ]
        )

    def strip_name_suffix(self):
        """A relational path ending with `.name` loses it before it is stored :
        `partner_id.commercial_partner_id.name` -> `partner_id.commercial_partner_id`.

        When the shorter name is already a column (`user_id.name` and `user_id`, the
        name Odoo shows of the many2one), that column is kept and the path dropped.
        """
        columns = set(self.df.columns)
        renames, dropped = {}, []
        for col in self.df.columns:
            if not col.endswith(".name"):
                continue
            short = col.removesuffix(".name")
            if short in columns or short in renames.values():
                dropped.append(col)
            else:
                renames[col] = short
        self.df = self.df.drop(dropped).rename(renames)

    def _fix_false_strings(self):
        self.df = self.df.with_columns(pl.col(pl.String).replace("false", ""))

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
        # significant decimals = digits left once the trailing zeros are gone
        significant = decimal_parts.str.strip_chars_end("0").str.len_chars()
        max_scale = significant.max()
        if max_scale is None:
            return pl.col(col_name)
        return pl.col(col_name).cast(pl.Decimal(scale=max_scale))

    def _is_date_field(self, name: str, field: dict) -> bool:
        """A date or datetime column : the type of the field decides. Only when the
        metadata gives no type is the name used (`prevalidated` holds "date" too)."""
        field_type = field.get("type")
        if field_type:
            return field_type in ("date", "datetime")
        return "date" in name and not self.df[name].is_null().all()

    def set_datetime_string2date_columns(self):
        fields = {k: v for k, v in (self.fields or {}).items() if isinstance(v, dict)}
        datetime_fields = [
            x
            for x in fields
            if x in self.df.columns and self._is_date_field(x, fields[x])
        ]
        self.df = self.df.with_columns(
            pl.col(datetime_fields).cast(pl.String).str.to_datetime(strict=False)
        )
        self.df = self.df.with_columns(pl.col(datetime_fields).cast(pl.Date))
        # the dotted relational paths (`order_id.date_order`) are not in the
        # fields metadata : same rule for every datetime column, the day is kept
        self.df = self.df.with_columns(pl.col(pl.Datetime).cast(pl.Date))

    def split_many2one_result(self):
        """Convert Many2one list fields to 2 columns.

        i.e. company_id [2, "My Company"] ->
            company_id: "My Company"
            company_id_: 2

        Every many2one of the fields metadata gets both columns, whatever its name
        (`product_uom`, `create_uid`...) : `<field>_` is always the id, so a tile can
        rely on it for a link or a grouping. A column that only looks like a many2one
        (a name with `_id` and a list of two values, not in the metadata) is split too.
        """
        m2o_fields = self._m2o_fields()
        for col in self.df.columns:
            is_m2o = col in m2o_fields
            if not is_m2o and not re.search(r"_(u?id)", col):
                continue
            id_col = f"{col}_" if is_m2o else re.sub(r"_(u?id)", "_id_", col)
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
        """Build the Df helper from a list of raw record dicts (id -> value)."""
        df = pl.DataFrame(raw_vals, strict=False, infer_schema_length=None)
        return cls(
            df,
            fields=metadata,
            decimal_truncate=decimal_truncate or env.decimal_truncate,
        )
