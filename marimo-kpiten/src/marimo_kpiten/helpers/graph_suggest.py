import polars as pl

from marimo_kpiten.services.i18n import t

MAX_DIM_DISTINCT = 50

_NUMERIC = (
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.Float32,
    pl.Float64,
    pl.Decimal,
)


def classify_columns(df: pl.DataFrame) -> dict[str, list[str]]:
    """Split columns into roles: date, dimension (X), measure (Y), other."""
    roles = {"date": [], "dimension": [], "measure": [], "other": []}
    for col in df.columns:
        dtype = df[col].dtype
        if dtype in (pl.Date, pl.Datetime):
            roles["date"].append(col)
        elif dtype in _NUMERIC:
            if col == "id" or col.endswith(("_id_", "_uid")):
                roles["other"].append(col)
            else:
                roles["measure"].append(col)
        elif dtype == pl.Utf8 and not df[col].is_null().all():
            n = df[col].n_unique()
            if 2 <= n <= MAX_DIM_DISTINCT:
                roles["dimension"].append(col)
            else:
                roles["other"].append(col)
        else:
            roles["other"].append(col)
    return roles


def suggest_x(df: pl.DataFrame) -> str | None:
    roles = classify_columns(df)
    if roles["date"]:
        return roles["date"][0]
    if roles["dimension"]:
        return roles["dimension"][0]
    return None


def suggest_y(df: pl.DataFrame) -> str | None:
    roles = classify_columns(df)
    return roles["measure"][0] if roles["measure"] else None


def suggest_aggregation(df: pl.DataFrame, column: str) -> str:
    if df[column].dtype in _NUMERIC:
        return "sum"
    return "count"


def suggest_graph_type(df: pl.DataFrame, x_column: str) -> str:
    if x_column and df[x_column].dtype in (pl.Date, pl.Datetime):
        return "area"
    return "bar"


def suggest_name(x_column: str | None, y_column: str | None) -> str:
    if not x_column or not y_column:
        return ""
    return t("Total {y} by {x}", y=y_column, x=x_column)
