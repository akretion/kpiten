import polars as pl
from decimal import Decimal


class Df:
    def __init__(self, df):
        self.df = df

    def get_df(self):
        self.remove_empty_columns()
        self.set_datetime2date_columns()
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

    def set_datetime2date_columns(self):
        self.df = self.df.with_columns(pl.col(pl.Datetime).cast(pl.Date))
