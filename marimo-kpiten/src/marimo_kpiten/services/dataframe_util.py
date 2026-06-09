import re
import polars as pl
from decimal import Decimal


class Df:
    def __init__(self, df, fields=None, decimal_truncate=None):
        self.df = df
        self.fields = fields
        self.decimal_truncate = decimal_truncate

    def get_df(self):
        # self.remove_empty_columns()
        self.set_datetime_string2date_columns()
        self.split_many2one_result()
        if self.decimal_truncate:
            self.df = self.df.with_columns(
                pl.col(pl.Decimal).round(self.decimal_truncate)
            )
            # TODO debug
            # self.df = self.df.with_columns(pl.col('margin_percent').round(self.decimal_truncate))
        # Normalize decimal
        self.df = self.df.with_columns(
            [
                self.normalize_decimal_col(self.df, col).alias(col)
                for col in self.get_decimal_columns()
            ]
        )
        return self.df

    def get_decimal_columns(self):
        "Get columns from Decimal type"
        return [
            name
            for name, dtype in zip(self.df.columns, self.df.dtypes)
            if isinstance(dtype, pl.Decimal)
        ]

    def normalize_decimal_col(self, df: pl.DataFrame, col_name: str) -> pl.Expr:
        """
        Reduces the scale of a Decimal column to the number of decimal places
        significant max in the column, keeping the Decimal type.
        """
        series = df[col_name]
        # Find the number of significant decimal places of each value
        as_str = series.cast(pl.String)
        decimal_parts = as_str.str.extract(r"\.(\d+)$", 1)
        # Remove trailing zeros to find significant decimal places
        significant = decimal_parts.map_elements(
            lambda s: len(s.rstrip("0")) if s else 0, return_dtype=pl.Int32
        )
        max_scale = significant.max()
        # Cast to Decimal avec la nouvelle scale
        return pl.col(col_name).cast(pl.Decimal(scale=max_scale))

    def remove_empty_columns(self):
        self.df = self.df.select(
            [col for col in self.df.columns if not self.df[col].is_null().all()]
        )

    def set_datetime_string2date_columns(self):
        datetime_fields = [
            x
            for x in self.fields
            if self.fields[x].get("type") == "datetime"
            and not self.df[x].is_null().all()
        ]
        print(datetime_fields)
        self.df = self.df.with_columns(pl.col(datetime_fields).str.to_datetime())
        self.df = self.df.with_columns(pl.col(datetime_fields).cast(pl.Date))

    def split_many2one_result(self):
        """Convert Many2one list fields to 2 fields
        i.e.
        company_id [2, "My Company"]
        =>
            company_id: My Company
            company_id_: 2

        Recognized columns: those with _id or _uid suffix
        """
        id_cols = [
            col
            for col in self.df.columns
            if re.search(r"_(u?id)$", col)
            and not self.df[col].is_null().all()
            and self.df[col].dtype is pl.List
        ]
        self.df = self.df.with_columns(
            [
                expr
                for col in id_cols
                for expr in [
                    pl.col(col)
                    .list.get(0)
                    .cast(pl.Int64)
                    .alias(re.sub(r"_(u?id)$", "_id_", col)),
                    pl.col(col).list.get(1).str.strip_chars().alias(col),
                ]
            ]
        )
