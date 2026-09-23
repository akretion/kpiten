"""Panel filters helpers from `kt.panel.filter_config` (framework agnostic).

filter_config JSON schema ::
    {"date": {"field": "date_order"},   # or a list : ["date_order", "order_id.date_order"]
     "dimensions": [{"name": "user_id", "label": "Salesperson"}]}

All expressions are polars predicates (list[pl.Expr]).
"""

import datetime

import polars as pl

from kpiten_core import config, date_filter, dimension, i18n

DATE_OPTIONS = {
    "": "full range",
    "today only": "today only",
    "last 7 days": "last 7 days",
    "last 30 days": "last 30 days",
    "last 90 days": "last 90 days",
    "last 180 days": "last 180 days",
    "last 365 days": "last 365 days",
    "year to date": "year to date",
    "last year": "last year",
    "last 5 years": "last 5 years",
}
# the dashboards open on it, like the Odoo dashboards (`last_three_months`)
DEFAULT_DATE_OPTION = "last 90 days"
WINDOWS = (7, 30, 90, 180, 365)  # days, the relative periods of an Odoo dashboard
MAX_MONTHS, MAX_YEARS = 12, 10


def date_range(
    store, filter_config: dict
) -> tuple[datetime.date, datetime.date] | None:
    """The first and last date of the panel's date column(s) in the user's rows
    (None when the panel has no date, or no row has one)."""
    fields = date_fields(filter_config)
    low = high = None
    for frame in store.values():
        lazy = frame.lazy()
        columns = set(lazy.collect_schema().names())
        for field in (f for f in fields if f in columns):
            bounds = lazy.select(
                pl.col(field).cast(pl.Date).min().alias("low"),
                pl.col(field).cast(pl.Date).max().alias("high"),
            ).collect(engine="streaming")
            first, last = bounds["low"][0], bounds["high"][0]
            if first is not None:
                low = first if low is None else min(low, first)
                high = last if high is None else max(high, last)
    return (low, high) if low is not None else None


def date_options(
    date_range_of_data, today: datetime.date | None = None
) -> dict[str, str]:
    """The choices of the Period filter that fit the data : the relative windows
    shorter than the data, year to date when it goes back before this year, then the
    calendar months (data of less than two years) or years (more) it covers, newest
    first. Without a range (no date, nothing loaded) the whole static list."""
    if date_range_of_data is None:
        return dict(DATE_OPTIONS)
    today = today or datetime.date.today()
    low, high = date_range_of_data
    span = (high - low).days + 1
    options = {"": "full range"}
    if high >= today:
        options["today only"] = "today only"
    for days in WINDOWS:
        # shorter than the data, and reaching it (old data : nothing in the last 7 days)
        if days < span and high >= today - datetime.timedelta(days=days - 1):
            options[f"last {days} days"] = f"last {days} days"
    if low < config.fiscal_year_start(today) <= high:
        options["year to date"] = "year to date"
    if span <= 730:
        months = []
        year, month = high.year, high.month
        while (year, month) >= (low.year, low.month) and len(months) < MAX_MONTHS:
            months.append(f"{year}-{month:02d}")
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        options.update({key: key for key in months})
    else:
        years = range(min(high.year, today.year - 1), low.year - 1, -1)
        options.update({str(y): str(y) for y in list(years)[:MAX_YEARS]})
    return options


def default_date_option(
    options: dict[str, str], date_range_of_data, today: datetime.date | None = None
) -> str:
    """The period a panel opens on : the one of `kt.config` (last 90 days) when the
    data reaches it, else the full range (an empty dashboard is of no use)."""
    default = config.default_period()
    if date_range_of_data is None:
        return default
    today = today or datetime.date.today()
    bounds = date_filter.bounds_for_option(default, today)  # None : the full range
    reached = bounds is None or date_range_of_data[1] >= bounds[0]
    return default if default in options and reached else ""


def bounds_of_option(option: str | None):
    """Start/end dates implied by a period option ('' stays None)."""
    return date_filter.bounds_for_option(option or None)


def date_fields(filter_config: dict) -> list[str]:
    """The date column(s) of the Period filter : one name, or a list for panels
    whose tables do not all call the date the same (`date_order` on the orders,
    `order_id.date_order` on their lines). A predicate on a column a table does
    not have is not applied to that table (see `tiles.filter_df`)."""
    field = (filter_config.get("date") or {}).get("field")
    if not field:
        return []
    return [field] if isinstance(field, str) else list(field)


def make_predicates(
    filter_config: dict, date_value, dim_values: dict[str, list]
) -> list[pl.Expr]:
    """Combine date range + selected dimension values into predicates."""
    exprs = []
    if date_value:
        for date_field in date_fields(filter_config):
            exprs += date_filter.process_dt_predicate(tuple(date_value), date_field)
    for dim in filter_config.get("dimensions", []):
        column = dim["name"]
        selected = dim_values.get(column)
        if selected:
            exprs.append(pl.col(column).is_in(selected))
    return exprs


def previous_bounds(date_value) -> tuple[datetime.date, datetime.date] | None:
    """The period right before `date_value`, the one a card compares itself with.
    None without a period.

    The same number of days, just before (Odoo shifts a relative period by its
    own length) ; a period that starts on the first day of the fiscal year (year to
    date ; January 1st unless `kt.config` says otherwise) goes back one year instead,
    like the year-to-date of Odoo."""
    if not date_value:
        return None
    start, end = date_value
    if start.day == 1 and (end + datetime.timedelta(days=1)).day == 1:
        # whole calendar months (a month, a year) : the same number of months before
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        year, month = divmod(start.year * 12 + start.month - 1 - months, 12)
        return date_filter.month_bounds(year, month + 1)[0], start - datetime.timedelta(
            days=1
        )
    if start.month == config.fiscal_start_month() and start.day == 1:
        try:
            return start.replace(year=start.year - 1), end.replace(year=end.year - 1)
        except ValueError:  # February 29th
            return (
                start.replace(year=start.year - 1),
                end.replace(year=end.year - 1, day=28),
            )
    previous_end = start - datetime.timedelta(days=1)
    return previous_end - (end - start), previous_end


def make_previous_predicates(
    filter_config: dict, date_value, dim_values: dict[str, list]
) -> list[pl.Expr] | None:
    """The predicates of the previous period, with the same dimension filters.
    None when there is no period to go back from (full range, no date column)."""
    previous = previous_bounds(date_value)
    if previous is None or not date_fields(filter_config):
        return None
    return make_predicates(filter_config, previous, dim_values)


def describe_previous(date_value) -> str | None:
    """`2026-04-20 → 2026-06-18`, the previous period as text (a tooltip)."""
    previous = previous_bounds(date_value)
    if previous is None:
        return None
    return f"{previous[0]:%Y-%m-%d} → {previous[1]:%Y-%m-%d}"


def dimension_choices(store: dict[str, pl.DataFrame], column: str) -> list[str]:
    return dimension.dimension_values(list(store.values()), column)


def describe_filters(
    filter_config: dict, date_value, dim_values: dict[str, list], tr=i18n.english
) -> str:
    """Human readable description of the active panel filters.

    Used as tile tooltip : « how was this data filtered » (date bounds on the
    date field + selected dimension values).
    """
    lines = []
    date_field = ", ".join(date_fields(filter_config))
    if date_field and date_value:
        start, end = date_value
        lines.append(
            tr(
                "Period {start} → {end} ({field})",
                start=f"{start:%Y-%m-%d}",
                end=f"{end:%Y-%m-%d}",
                field=date_field,
            )
        )
    for dim in filter_config.get("dimensions", []):
        selected = dim_values.get(dim["name"])
        label = dim.get("label") or dim["name"]
        if selected:
            lines.append(f"{label}: {', '.join(map(str, selected))}")
    return "\n".join(lines)
