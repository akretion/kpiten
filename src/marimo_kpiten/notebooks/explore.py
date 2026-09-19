import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Data explorer")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    from kpiten_core import filters
    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from marimo_kpiten import ai, gallery, kpi_view, recipes, ui

    return Backend, ai, filters, gallery, kpi_view, mo, pl, recipes, ui, user_store


@app.cell
def _(mo, ui):
    # set by the server (`SsoMiddleware`) from the session cookie : the browser
    # cannot choose it
    meta = mo.app_meta().request.meta
    user_id, db = meta["user_id"], meta["db"]
    ui.header("explore", user_id, db)
    return db, user_id


@app.cell
def _(Backend, db, mo, ui, user_id, user_store):
    # the tables of the parquet store, restricted to this user (ACL + record rules)
    backend = Backend.create(db=db)
    ui.load_settings(backend)  # the switches of the AI, the number format...
    store = user_store(backend, user_id)
    mo.stop(not store, mo.callout("No data source in your scope.", kind="warn"))
    return (store,)


@app.cell
def _(mo, store):
    source = mo.ui.dropdown(
        sorted(store),
        value="purchase.order" if "purchase.order" in store else sorted(store)[0],
        label="Data source",
    )
    source
    return (source,)


@app.cell
def _(mo, pl, source, store, ui):
    frame = store[source.value]
    _schema = frame.collect_schema()
    _rows = frame.select(pl.len()).collect().item()
    _columns = pl.DataFrame(
        {"column": _schema.names(), "type": [str(t) for t in _schema.dtypes()]}
    )
    mo.vstack(
        [
            mo.md(f"**{_rows:,}** rows · **{len(_schema)}** columns".replace(",", " ")),
            mo.accordion(
                {
                    "Columns": mo.ui.table(_columns, selection=None, page_size=15),
                    "First rows": mo.ui.table(
                        ui.plain(frame.head(20).collect()), selection=None
                    ),
                }
            ),
        ]
    )
    return (frame,)


@app.cell
def _(filters, frame, mo, pl, recipes):
    # Build a KPI : the choices, made of the columns of the table
    _schema = frame.collect_schema()
    _numeric = [
        c
        for c, t in _schema.items()
        if t.is_numeric() and c != "id" and not c.endswith("_")
    ]
    _texts = [c for c, t in _schema.items() if t == pl.String]
    _dates = [c for c, t in _schema.items() if t in (pl.Date, pl.Datetime)]

    def _pick(options, *preferred):
        return next((c for c in preferred if c in options), (options or [None])[0])

    def _labelled(options: dict, key):
        """A dropdown of {label: key} opened on `key`."""
        return {label: k for k, label in options.items()}, options[key]

    _outputs, _output_label = _labelled(recipes.OUTPUTS, "ranking")
    _aggregations, _aggregation_label = _labelled(recipes.AGGREGATIONS, "sum")
    _highlights, _highlight_label = _labelled(recipes.HIGHLIGHTS, "none")
    _periods, _period_label = _labelled(filters.date_options(None), "")

    output = mo.ui.dropdown(_outputs, value=_output_label, label="Show as")
    measure = mo.ui.dropdown(
        _numeric,
        value=_pick(_numeric, "amount_untaxed", "amount_total", "price_subtotal"),
        label="Measure",
    )
    aggregation = mo.ui.dropdown(
        _aggregations, value=_aggregation_label, label="Computed as"
    )
    group_by = mo.ui.dropdown(
        _texts,
        value=_pick(
            _texts, "partner_id.commercial_partner_id.name", "user_id.name", "state"
        ),
        label="Group by",
    )
    columns_by = mo.ui.dropdown(
        _texts,
        value=_pick(_texts, "state", "partner_id.country_id.name", "company_id"),
        label="Columns of the pivot",
    )
    date = mo.ui.dropdown(_dates, value=_pick(_dates, "date_order"), label="Date")
    grain = mo.ui.dropdown(
        {"Month": "month", "Quarter": "quarter", "Year": "year"},
        value="Month",
        label="Per",
    )
    period = mo.ui.dropdown(_periods, value=_period_label, label="Period")
    filter_column = mo.ui.dropdown(
        {"(no filter)": "", **{c: c for c in _texts}},
        value="(no filter)",
        label="Filter on",
    )
    top = mo.ui.number(start=1, stop=100, value=10, label="Top")
    add_share = mo.ui.checkbox(label="Add the share of the total")
    highlight = mo.ui.dropdown(_highlights, value=_highlight_label, label="Highlight")
    highlight_value = mo.ui.number(start=0, stop=1000, value=20, label="X")
    return (
        add_share,
        aggregation,
        columns_by,
        date,
        filter_column,
        grain,
        group_by,
        highlight,
        highlight_value,
        measure,
        output,
        period,
        top,
    )


@app.cell
def _(filter_column, frame, mo, pl):
    # the values of the column to filter on (the first 200)
    _column = filter_column.value
    _values = (
        frame.select(pl.col(_column).drop_nulls().unique().sort().head(200))
        .collect()[_column]
        .to_list()
        if _column
        else []
    )
    filter_values = mo.ui.multiselect(_values, label="Keep only")
    return (filter_values,)


@app.cell
def _(
    add_share,
    aggregation,
    columns_by,
    date,
    filter_column,
    filter_values,
    gallery,
    grain,
    group_by,
    highlight,
    highlight_value,
    measure,
    mo,
    output,
    period,
    top,
):
    # only the choices the chosen output uses
    _kind = output.value
    _rows = [mo.hstack([output, measure, aggregation], justify="start", gap=1)]
    if _kind in ("ranking", "table", "pivot"):
        _grouping = [group_by] + ([columns_by] if _kind == "pivot" else [])
        _rows.append(mo.hstack(_grouping, justify="start", gap=1))
    if _kind in ("trend", "card"):
        _when = [date] + ([grain] if _kind == "trend" else []) + [period]
        _rows.append(mo.hstack(_when, justify="start", gap=1))
    _rows.append(mo.hstack([filter_column, filter_values], justify="start", gap=1))
    _options = ([top] if _kind in ("ranking", "pivot") else []) + (
        [add_share] if _kind in ("ranking", "table") else []
    )
    if _kind in ("ranking", "table", "pivot"):
        _options += [highlight] + (
            [highlight_value] if highlight.value in ("share", "top") else []
        )
    if _options:
        _rows.append(mo.hstack(_options, justify="start", gap=1))
    mo.vstack(
        [
            mo.md("## Build a KPI"),
            mo.vstack(_rows),
            mo.Html(
                gallery.gallery(
                    output.value,
                    highlight.value if _kind in ("ranking", "table", "pivot") else "",
                )
            ),
        ]
    )
    return


@app.cell
def _(
    add_share,
    aggregation,
    columns_by,
    date,
    filter_column,
    filter_values,
    frame,
    grain,
    group_by,
    highlight,
    highlight_value,
    kpi_view,
    measure,
    output,
    period,
    recipes,
    top,
):
    kpi_view.render(
        recipes.Recipe(
            output=output.value,
            measure=measure.value,
            aggregation=aggregation.value,
            group_by=group_by.value,
            columns_by=columns_by.value,
            date=date.value,
            grain=grain.value,
            period=period.value,
            filter_column=filter_column.value or None,
            filter_values=list(filter_values.value),
            top=int(top.value),
            add_share=add_share.value,
            # only the outputs that offer it (a hidden choice must not apply)
            highlight=(
                highlight.value
                if output.value in ("ranking", "table", "pivot")
                else "none"
            ),
            highlight_value=highlight_value.value,
        ),
        frame,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Ask the AI
    """)
    return


@app.cell
def _(ai, mo):
    mo.stop(
        not ai.enabled(),
        mo.callout(
            "The AI is turned off in the KpiTen configuration (Odoo).", kind="warn"
        ),
    )
    available = ai.providers()
    mo.stop(
        not available,
        mo.callout(
            mo.md(
                "**No AI configured.** Set `ANTHROPIC_API_KEY` (Claude) or "
                "`LOCAL_LLM_MODEL` and `LOCAL_LLM_URL` (a local model, Ollama for "
                "example) in `.env`, then restart marimo."
            ),
            kind="warn",
        ),
    )
    provider = mo.ui.dropdown(
        {p.label: key for key, p in available.items()},
        value=next(iter(p.label for p in available.values())),
        label="Model",
    )
    provider
    return available, provider


@app.cell
def _(ai, available, frame, mo, provider, source):
    _chosen = available[provider.value]
    with mo.status.spinner("Reading the columns..."):
        description = ai.describe(frame)
    skills = ai.skills_for(source.value)  # how to write the code, what the words mean
    if not _chosen.leaves_machine:
        _sent = "Nothing leaves this machine : the model is local."
    else:
        _sent = (
            f"Sent to {_chosen.label} : the name and type of the columns"
            + (
                ", the few values of the columns that have few"
                if ai.sends_values()
                else ""
            )
            + " and your questions. No row. The code it writes runs here, on the "
            "rows you may read."
        )
    _sent += "\n\nSkills given to the model : " + (
        ", ".join(f"`{s.name}`" for s in skills) or "none"
    )
    mo.callout(mo.md(_sent), kind="info")
    return description, skills


@app.cell
def _(ai, available, description, frame, mo, provider, skills, ui):
    _provider = available[provider.value]
    _history = []  # what was said, for the next question (a new source starts over)

    def _model(messages, config):
        answer = ai.ask(
            _provider,
            frame,
            description,
            _history,
            messages[-1].content,
            skills=skills,
        )
        _history.extend(answer.exchange)
        del _history[:-12]
        return ui.ai_answer(answer)

    chat = mo.ui.chat(
        _model,
        prompts=[
            "Which columns are worth looking at?",
            "Count the rows by state, or by another category",
        ],
        max_height=700,
    )
    chat
    return (chat,)


if __name__ == "__main__":
    app.run()
