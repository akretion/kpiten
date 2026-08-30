import polars as pl

MAX_DISTINCT = 50
MIN_DISTINCT = 2


def dimension_options(dfs: list[pl.DataFrame]) -> list[str]:
    """String columns across the tables suitable as dimension filters."""
    options = set()
    for df in dfs:
        for col in df.columns:
            if df[col].dtype == pl.Utf8 and not df[col].is_null().all():
                n = df[col].n_unique()
                if MIN_DISTINCT <= n <= MAX_DISTINCT:
                    options.add(col)
    return sorted(options)


def dimension_values(dfs: list[pl.DataFrame], column: str) -> list[str]:
    """Distinct sorted values of a column across the tables that have it."""
    series = [
        df[column] for df in dfs if column in df.columns and not df[column].is_null().all()
    ]
    if not series:
        return []
    return pl.concat(series).unique().sort().to_list()