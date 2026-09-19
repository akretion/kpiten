import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Data explorer")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from marimo_kpiten import ai, ui

    return Backend, ai, mo, pl, ui, user_store


@app.cell
def _(mo, ui):
    # set by the server (`SsoMiddleware`) from the session cookie : the browser
    # cannot choose it
    meta = mo.app_meta().request.meta
    user_id, db = meta["user_id"], meta["db"]
    ui.header("explore", user_id, db)
    return db, user_id


@app.cell
def _(Backend, db, mo, user_id, user_store):
    # the tables of the parquet store, restricted to this user (ACL + record rules)
    store = user_store(Backend.create(db=db), user_id)
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
def _(ai, mo):
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
