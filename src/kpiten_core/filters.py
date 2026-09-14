"""Panel filters helpers from `kt.panel.filter_config` (framework agnostic).

filter_config JSON schema ::
    {"date": {"field": "date_order"},
     "dimensions": [{"name": "user_id.name", "label": "Salesperson"}]}

All expressions are polars predicates (list[pl.Expr]).
"""

import polars as pl

from kpiten_core import date_filter, dimension

DATE_OPTIONS = {
    "": "full range",
    "today only": "today only",
    "last week": "last week",
    "last 30 days": "last 30 days",
    "last 90 days": "last 90 days",
    "last 6 months": "last 6 months",
    "last 5 years": "last 5 years",
}


def bounds_of_option(option: str | None):
    """Start/end dates implied by a period option ('' stays None)."""
    return date_filter.bounds_for_option(option or None)


def make_predicates(
    filter_config: dict, date_value, dim_values: dict[str, list]
) -> list[pl.Expr]:
    """Combine date range + selected dimension values into predicates."""
    exprs = []
    date_field = (filter_config.get("date") or {}).get("field")
    if date_field and date_value:
        exprs += date_filter.process_dt_predicate(tuple(date_value), date_field)
    for dim in filter_config.get("dimensions", []):
        column = dim["name"]
        selected = dim_values.get(column)
        if selected:
            exprs.append(pl.col(column).is_in(selected))
    return exprs


def dimension_choices(store: dict[str, pl.DataFrame], column: str) -> list[str]:
    return dimension.dimension_values(list(store.values()), column)


def describe_filters(
    filter_config: dict, date_value, dim_values: dict[str, list]
) -> str:
    """Human readable description of the active panel filters.

    Used as tile tooltip : « how was this data filtered » (date bounds on the
    date field + selected dimension values).
    """
    lines = []
    date_field = (filter_config.get("date") or {}).get("field")
    if date_field and date_value:
        start, end = date_value
        lines.append(
            f"Period {start:%Y-%m-%d} → {end:%Y-%m-%d} ({date_field})"
        )
    for dim in filter_config.get("dimensions", []):
        selected = dim_values.get(dim["name"])
        label = dim.get("label") or dim["name"]
        if selected:
            lines.append(f"{label}: {', '.join(map(str, selected))}")
    return "\n".join(lines)
