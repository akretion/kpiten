import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Data explorer")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    from kpiten_core import config, filters
    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from marimo_kpiten import ai, gallery, kpi_view, recipes, ui

    return (
        Backend,
        ai,
        config,
        filters,
        gallery,
        kpi_view,
        mo,
        pl,
        recipes,
        ui,
        user_store,
    )


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
    return backend, store


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
    _highlights, _highlight_label = _labelled(recipes.highlights(), "none")
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
    alert = mo.ui.dropdown(
        {
            "No alert": "none",
            "Alert above": "alert_above",
            "Alert below": "alert_below",
        },
        value="No alert",
        label="Alert",
    )
    return (
        add_share,
        aggregation,
        columns_by,
        date,
        filter_column,
        grain,
        group_by,
        alert,
        highlight,
        measure,
        output,
        period,
        top,
    )


@app.cell
def _(alert, highlight, mo, output, recipes):
    # the value a highlight asks for : its name and its default depend on the mode
    _mode = alert.value if output.value == "card" else highlight.value
    _default, _what = recipes.HIGHLIGHT_VALUE.get(_mode, (20, "X"))
    highlight_value = mo.ui.number(start=0, stop=1_000_000, value=_default, label=_what)
    return (highlight_value,)


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
    alert,
    columns_by,
    config,
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
            []
            if highlight.value in ("none", "above_average", "heatmap")
            else [highlight_value]
        )
    if _kind == "card" and config.feature("alerts"):
        _options += [alert] + ([highlight_value] if alert.value != "none" else [])
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
    alert,
    columns_by,
    date,
    filter_column,
    filter_values,
    grain,
    group_by,
    highlight,
    highlight_value,
    measure,
    output,
    period,
    recipes,
    top,
):
    recipe = recipes.Recipe(
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
            alert.value
            if output.value == "card"
            else (
                highlight.value
                if output.value in ("ranking", "table", "pivot")
                else "none"
            )
        ),
        highlight_value=highlight_value.value,
    )
    return (recipe,)


@app.cell
def _(frame, kpi_view, recipe):
    kpi_view.render(recipe, frame)
    return


@app.cell
def _(backend, config, mo, recipe, recipes, user_id):
    # Save the KPI as a tile of a panel : a KpiTen manager, when kt.config turns it on
    mo.stop(not config.feature("save_tile") or recipes.missing(recipe) is not None)
    mo.stop(
        not backend.can_edit_tiles(user_id),
        mo.callout("Only a KpiTen manager can save a KPI as a tile.", kind="neutral"),
    )
    _panels = {p["name"]: p["id"] for p in backend.get_panels()}
    mo.stop(not _panels, mo.callout("There is no panel to save it in.", kind="warn"))
    save_panel = mo.ui.dropdown(_panels, value=next(iter(_panels)), label="Panel")
    save_name = mo.ui.text(
        value=recipes.title(recipe)[:80], label="Name of the tile", full_width=True
    )
    save_run = mo.ui.run_button(label="Save as a tile")
    mo.hstack([save_panel, save_name, save_run], justify="start", gap=1, align="end")
    return save_name, save_panel, save_run


@app.cell
def _(backend, mo, recipe, recipes, save_name, save_panel, save_run, source, user_id):
    mo.stop(not save_run.value)
    backend.create_tile(
        model=source.value,
        definition=recipes.tile_definition(recipe),
        kind="data",
        name=save_name.value.strip() or recipes.title(recipe),
        user_id=user_id,
        panel_id=save_panel.value,
    )
    mo.callout(
        mo.md(
            f"**Saved** in the panel _{save_panel.selected_key}_ : reload the dashboard."
        ),
        kind="success",
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
def _(available, config, mo, recipe, recipes):
    # Refine the KPI built above with the AI, when kt.config turns it on
    mo.stop(not config.feature("ai_refine") or recipes.missing(recipe) is not None)
    refine_text = mo.ui.text_area(
        placeholder="e.g. only the confirmed orders, and add the vendor country",
        label="Change the KPI above",
        rows=2,
        full_width=True,
    )
    refine_run = mo.ui.run_button(label="Refine with the AI")
    mo.vstack([refine_text, refine_run])
    return refine_run, refine_text


@app.cell
def _(
    ai,
    available,
    description,
    frame,
    mo,
    provider,
    recipe,
    recipes,
    refine_run,
    refine_text,
    skills,
    ui,
):
    mo.stop(not refine_run.value or not refine_text.value.strip())
    with mo.status.spinner("Asking the model..."):
        _answer = ai.ask(
            available[provider.value],
            frame,
            description,
            recipes.seed_messages(recipe),
            refine_text.value.strip(),
            skills=skills,
        )
    mo.vstack([mo.md("**The AI's answer**"), ui.ai_answer(_answer)])
    return


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


@app.cell(hide_code=True)
def _(ui):
    ui.footer()
    return


if __name__ == "__main__":
    app.run()
