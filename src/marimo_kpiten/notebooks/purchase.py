import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Purchase analysis")


@app.cell
def _():
    import altair as alt
    import marimo as mo
    import polars as pl

    from kpiten_core import filters
    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from kpiten_core.numfmt import format_number
    from marimo_kpiten import ui

    return Backend, alt, filters, format_number, mo, pl, ui, user_store


@app.cell
def _(mo, ui):
    # set by the server (`SsoMiddleware`) from the session cookie : the browser
    # cannot choose it
    meta = mo.app_meta().request.meta
    user_id, db = meta["user_id"], meta["db"]
    ui.header("purchase", user_id, db)
    return db, user_id


@app.cell
def _(Backend, db, mo, pl, ui, user_id, user_store):
    # lazy scans restricted to this user (ACL + record rules), then the orders in memory
    backend = Backend.create(db=db)
    ui.load_settings(backend)  # number format... of kt.config
    odoo_url = backend.get_base_url().rstrip("/")
    store = user_store(backend, user_id)
    # a table the user may not read is not in the store
    mo.stop(
        "purchase.order" not in store,
        mo.callout("You have no access to purchase orders.", kind="warn"),
    )
    _lazy = store["purchase.order"]
    _money = [c for c, t in _lazy.collect_schema().items() if t.is_decimal()]
    orders = _lazy.with_columns(pl.col(_money).cast(pl.Float64)).collect()
    mo.stop(
        orders.is_empty(),
        mo.callout("No purchase order in your scope.", kind="warn"),
    )
    return backend, odoo_url, orders


@app.cell
def _(filters, mo, orders):
    _range = (orders["date_order"].min(), orders["date_order"].max())
    _options = filters.date_options(_range)
    _default = filters.default_date_option(_options, _range)
    period = mo.ui.dropdown(
        {label: key for key, label in _options.items()},
        value=_options[_default],
        label="Period",
    )
    states = mo.ui.multiselect(
        sorted(orders["state"].drop_nulls().unique()),
        value=["purchase", "done"],
        label="Status",
    )
    # what a chart groups by, among the columns this user may read
    DIMENSIONS = {
        "Vendor": "partner_id.commercial_partner_id.name",
        "Buyer": "user_id.name",
        "Country": "partner_id.country_id.name",
        "Company": "company_id",
    }
    DIMENSIONS = {k: v for k, v in DIMENSIONS.items() if v in orders.columns}
    group_by = mo.ui.dropdown(
        DIMENSIONS, value=next(iter(DIMENSIONS)), label="Group by"
    )
    mo.hstack([period, states, group_by], justify="start", gap=2)
    return group_by, period, states


@app.cell
def _(filters, orders, pl, period, states):
    bounds = filters.bounds_of_option(period.value)
    previous = filters.previous_bounds(bounds)

    def pick(frame, window):
        frame = frame.filter(pl.col("state").is_in(states.value))
        if window:
            frame = frame.filter(pl.col("date_order").is_between(*window))
        return frame

    current = pick(orders, bounds)
    before = pick(orders, previous) if previous else None
    return before, bounds, current, previous


@app.cell
def _(before, current, filters, format_number, bounds, mo):
    def card(label, value, past, decimals=0, unit=""):
        caption = None
        direction = None
        if past:
            change = (value - past) / past * 100
            direction = "increase" if change >= 0 else "decrease"
            caption = f"{change:+.0f} % vs {filters.describe_previous(bounds)}"
        return mo.stat(
            value=f"{format_number(value, decimals)}{unit}",
            label=label,
            caption=caption,
            direction=direction,
            bordered=True,
        )

    def totals(frame):
        if frame is None:
            return 0, 0.0, 0.0
        n = frame.height
        spend = frame["amount_untaxed"].sum()
        return n, spend, (spend / n if n else 0.0)

    _n, _spend, _avg = totals(current)
    _pn, _pspend, _pavg = totals(before)
    mo.hstack(
        [
            card("Orders", _n, _pn),
            card("Spend (untaxed)", _spend, _pspend),
            card("Average order", _avg, _pavg),
        ],
        justify="start",
        gap=1,
    )
    return


@app.cell
def _(alt, current, mo, pl):
    _monthly = (
        current.group_by(pl.col("date_order").dt.truncate("1mo").alias("Month"))
        .agg(pl.col("amount_untaxed").sum().alias("Spend"))
        .sort("Month")
    )
    mo.ui.altair_chart(
        alt.Chart(_monthly, title="Monthly spend")
        .mark_bar()
        .encode(
            x=alt.X("Month:O", timeUnit="yearmonth", title=None),
            y=alt.Y("Spend:Q", title=None),
            tooltip=[
                alt.Tooltip("Month:T", format="%B %Y"),
                alt.Tooltip("Spend:Q", format=",.0f"),
            ],
        )
        .properties(width="container", height=220),
        chart_selection=False,
        legend_selection=False,
    )
    return


@app.cell
def _(alt, current, group_by, mo, pl):
    _label = next(k for k, v in group_by.options.items() if v == group_by.value)
    _top = (
        current.group_by(pl.col(group_by.value).alias(_label))
        .agg(
            pl.col("amount_untaxed").sum().alias("Spend"),
            pl.len().alias("Orders"),
        )
        .sort("Spend", descending=True)
        .head(10)
    )
    top_chart = mo.ui.altair_chart(
        alt.Chart(_top, title=f"Top 10 by spend : {_label.lower()}")
        .mark_bar()
        .encode(
            y=alt.Y(f"{_label}:N", sort="-x", title=None),
            x=alt.X("Spend:Q", title=None),
            tooltip=[_label, alt.Tooltip("Spend:Q", format=",.0f"), "Orders:Q"],
        )
        .properties(width="container", height=280),
        legend_selection=False,
    )
    mo.vstack(
        [top_chart, mo.md("<small>Click a bar to list its orders below.</small>")]
    )
    return (top_chart,)


@app.cell
def _(backend, current, group_by, mo, odoo_url, pl, top_chart, ui):
    # the orders behind the clicked bars (all of them without a click)
    _label = top_chart.value.columns[0] if top_chart.value.height else None
    _detail = (
        current.filter(pl.col(group_by.value).is_in(top_chart.value[_label]))
        if _label
        else current
    )
    _columns = {
        "date_order": "Date",
        "name": "Order",
        "partner_id.commercial_partner_id.name": "Vendor",
        "user_id.name": "Buyer",
        "state": "Status",
        "amount_untaxed": "Untaxed",
    }
    _shown = _detail.sort("date_order", descending=True).select(
        "id", *[pl.col(c).alias(a) for c, a in _columns.items() if c in _detail.columns]
    )
    # the order opens in Odoo (another tab)
    _rows = [
        {
            **{k: v for k, v in row.items() if k != "id"},
            "Order": ui.odoo_link(
                row["Order"], f"{odoo_url}/odoo/purchase.order/{row['id']}"
            ),
        }
        for row in _shown.to_dicts()
    ]
    # the same orders, as a list in Odoo (when the feature is on)
    _open = ui.records_link(backend, odoo_url, "purchase.order", _shown["id"].to_list())
    mo.vstack(
        [
            mo.md(f"**{len(_rows)}** orders" + (" (selection)" if _label else "")),
            *([_open] if _open else []),
            mo.ui.table(_rows, selection=None, page_size=10),
        ]
    )
    return


@app.cell
def _(current, mo):
    mo.accordion({"Explore every column of these orders": mo.ui.data_explorer(current)})
    return


if __name__ == "__main__":
    app.run()
