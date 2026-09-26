import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Step by step")


@app.cell
def _():
    import marimo as mo

    from kpiten_core import anonymize, derived
    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from marimo_kpiten import ai, ui

    try:
        import derived_kpiten
    except ImportError:  # the plugin is not in the venv of marimo (make apps)
        derived_kpiten = None
    return Backend, ai, anonymize, derived, derived_kpiten, mo, ui, user_store


@app.cell
def _(mo, ui):
    # set by the server (`SsoMiddleware`) from the session cookie : the browser
    # cannot choose it
    meta = mo.app_meta().request.meta
    user_id, db = meta["user_id"], meta["db"]
    ui.header("derived", user_id, db)
    return db, user_id


@app.cell
def _(Backend, db, derived_kpiten, mo, ui, user_id, user_store):
    mo.stop(
        derived_kpiten is None,
        mo.callout(
            "The plugin derived-kpiten is not installed (make apps).", kind="warn"
        ),
    )
    # the tables of the parquet store, restricted to this user (ACL + record rules)
    backend = Backend.create(db=db)
    ui.load_settings(backend)
    store = user_store(backend, user_id)
    mo.stop(not store, mo.callout("No data source in your scope.", kind="warn"))
    manager = backend.can_edit_tiles(user_id)  # a KpiTen manager : the detail
    return backend, manager, store


@app.cell
def _(mo):
    # bumped when a derived table is saved : the list is read again
    get_version, set_version = mo.state(0)
    # the mode : the result of the query, or its steps explained
    get_mode, set_mode = mo.state("query")
    # the language of the query : SQL (polars SQL) or polars (a chain of methods)
    get_lang, set_lang = mo.state("sql")
    return get_lang, get_mode, get_version, set_lang, set_mode, set_version


@app.cell
def _(backend, derived, get_version, mo, store, user_id):
    get_version()
    # the derived tables (kt.derived.table) : the user's own and the shared ones,
    # computed on the rows of this user ; a query reads them by their name
    definitions = backend.get_derived_tables(user_id)
    derived_tables, _errors = derived.resolve(store, definitions)
    (
        mo.md(
            "<small>Derived tables left out : "
            + " ; ".join(f"`{name}` ({why})" for name, why in _errors.items())
            + "</small>"
        )
        if _errors
        else None
    )
    return definitions, derived_tables


@app.cell
def _(mo, store):
    source = mo.ui.dropdown(
        sorted(store),
        value="sale.order" if "sale.order" in store else sorted(store)[0],
        label="Table `d`",
    )
    return (source,)


@app.cell
def _(get_lang, get_mode, mo, set_lang, set_mode, source):
    MODES = {"Result": "query", "Step by step": "steps"}
    mode = mo.ui.radio(
        MODES,
        value=next(label for label, key in MODES.items() if key == get_mode()),
        on_change=set_mode,
        inline=True,
    )
    LANGUAGES = {"SQL": "sql", "Polars": "polars"}
    language = mo.ui.radio(
        LANGUAGES,
        value=next(label for label, key in LANGUAGES.items() if key == get_lang()),
        on_change=set_lang,
        inline=True,
    )
    mo.vstack(
        [
            mo.hstack([source, mode, language], justify="start", align="center", gap=3),
            mo.md(
                "<small>The query reads the table as `d`, the others by their name "
                'in quotes (`"sale.order.line"`), in polars `tables["sale.order.line"]`. '
                "Step by step : one step per `WITH` block (its words in the `--` comment "
                "above it) or per clause ; in polars one per method (its `#` comment)."
                "</small>"
            ),
        ]
    )
    return


@app.cell
def _():
    # a first query for the tables of the demo, the first rows for the others
    EXAMPLES = {
        "sale.order": """WITH
-- Step 1 : the confirmed orders
confirmed AS (SELECT * FROM d WHERE state = 'sale' AND amount_untaxed > 0),
-- Step 2 : the month of each order
with_month AS (SELECT *, strftime(date_order, '%Y-%m') AS month FROM confirmed),
-- Step 3 : the total by salesperson and month
by_user AS (
    SELECT user_id, month, SUM(amount_untaxed) AS untaxed, COUNT(*) AS orders
    FROM with_month
    GROUP BY user_id, month
)
-- Step 4 : the 10 best months
SELECT * FROM by_user ORDER BY untaxed DESC LIMIT 10""",
        "sale.order.line": """WITH
-- Step 1 : the lines of the confirmed orders
confirmed AS (SELECT * FROM d WHERE state = 'sale'),
-- Step 2 : the salesperson of the order of each line
with_user AS (
    SELECT l.*, o.user_id AS salesperson
    FROM confirmed l JOIN "sale.order" o ON l.order_id_ = o.id
),
-- Step 3 : what each salesperson sells of each category
by_category AS (
    SELECT salesperson, "product_id.categ_id.complete_name" AS category,
           SUM(price_subtotal) AS untaxed
    FROM with_user
    GROUP BY salesperson, category
)
-- Step 4 : the largest first
SELECT * FROM by_category ORDER BY untaxed DESC LIMIT 15""",
        "purchase.order": """WITH
-- Step 1 : the orders, not the requests for quotation
orders AS (SELECT * FROM d WHERE state IN ('purchase', 'done')),
-- Step 2 : the days from the order to the planned delivery
with_delay AS (
    -- a date cast to an integer : its number of days
    SELECT *, CAST(date_planned AS INTEGER) - CAST(date_order AS INTEGER) AS days
    FROM orders
),
-- Step 3 : the spend and the delay by vendor
by_vendor AS (
    SELECT partner_id AS vendor, SUM(amount_untaxed) AS spend,
           AVG(days) AS average_days, COUNT(*) AS orders
    FROM with_delay
    GROUP BY partner_id
)
-- Step 4 : the 10 largest vendors
SELECT * FROM by_vendor ORDER BY spend DESC LIMIT 10""",
    }
    FIRST_ROWS = """-- Step 1 : the first rows of the table
SELECT * FROM d LIMIT 10"""
    POLARS_EXAMPLES = {
        "sale.order": """d_next = (
    d
    # the confirmed orders
    .filter((pl.col("state") == "sale") & (pl.col("amount_untaxed") > 0))
    # the month of each order
    .with_columns(pl.col("date_order").dt.to_string("%Y-%m").alias("month"))
    # the total by salesperson and month
    .group_by("user_id", "month")
    .agg(pl.col("amount_untaxed").sum().alias("untaxed"), pl.len().alias("orders"))
    # the 10 best months
    .sort("untaxed", descending=True)
    .head(10)
)""",
    }
    POLARS_FIRST_ROWS = """d_next = (
    d
    # the first rows of the table
    .head(10)
)"""
    return EXAMPLES, FIRST_ROWS, POLARS_EXAMPLES, POLARS_FIRST_ROWS


@app.cell
def _(EXAMPLES, FIRST_ROWS, POLARS_EXAMPLES, POLARS_FIRST_ROWS, mo, source):
    # the query of the editor, that the AI may replace ; a new table starts over
    get_sql, set_sql = mo.state(EXAMPLES.get(source.value, FIRST_ROWS))
    get_py, set_py = mo.state(POLARS_EXAMPLES.get(source.value, POLARS_FIRST_ROWS))
    get_answer, set_answer = mo.state(None)  # the last answer of the AI
    get_current, set_current = mo.state(None)  # the derived table opened or saved
    get_clip, set_clip = mo.state(None)  # the prompt to copy to a chat
    return (
        get_answer,
        get_clip,
        get_current,
        get_py,
        get_sql,
        set_answer,
        set_clip,
        set_current,
        set_py,
        set_sql,
    )


@app.cell
def _(definitions, mo, set_current, set_lang, set_py, set_sql, source):
    # open a derived table of this table `d` (or of none) : its query in the editor
    _tables = {
        d["name"] + (" (shared)" if d["shared"] else ""): d
        for d in definitions
        if d.get("source") in (source.value, "", None)
    }

    def _open(chosen):
        if chosen:
            _lang = chosen.get("language") or "sql"
            (set_py if _lang == "polars" else set_sql)(chosen["sql"])
            set_lang(_lang)
            set_current(chosen)

    opener = (
        mo.ui.dropdown(
            _tables,
            label="::lucide:folder-open:: Open a derived table",
            on_change=_open,
        )
        if _tables
        else None
    )
    opener
    return


@app.cell
def _(ai, derived_tables, manager, mo, source, store):
    # Ask the AI : it writes the query in steps (skill steps.md of derived-kpiten). A
    # KpiTen manager may also ask a chat of their own (ChatGPT, Mistral...) by copy and
    # paste : what is copied goes out of KpiTen, always with pseudonyms
    CLIPBOARD = "clipboard"
    available = ai.providers() if ai.enabled() else {}
    _choices = {p.label: key for key, p in available.items()}
    if manager and ai.enabled():
        _choices["Copy and paste (ChatGPT, Mistral...)"] = CLIPBOARD
    if not _choices:
        _out = mo.md(
            "<small>No AI here : turned off in the KpiTen configuration, or none "
            "configured (`ANTHROPIC_API_KEY`, `LOCAL_LLM_MODEL` in `.env`).</small>"
        )
        provider = question = ask_button = joins = None
    else:
        provider = mo.ui.dropdown(_choices, value=next(iter(_choices)), label="Model")
        # the columns of the tables it may join : only those chosen (a small local
        # model reads a short prompt only)
        joins = mo.ui.multiselect(
            [name for name in sorted(store) if name != source.value]
            + sorted(derived_tables),
            label="Tables to join",
        )
        question = mo.ui.text_area(
            placeholder="The confirmed sales of 2025 by month and salesperson, "
            "or : now only the customers of France",
            full_width=True,
            rows=2,
        )
        ask_button = mo.ui.run_button(label="✨ Ask the AI")
        _out = mo.vstack(
            [
                mo.hstack([question, ask_button], align="end", widths=[5, 1]),
                mo.hstack([provider, joins], justify="start", align="start"),
            ]
        )
    _out
    return CLIPBOARD, ask_button, available, joins, provider, question


@app.cell
def _(CLIPBOARD, ai, anonymize, available, backend, mo, provider, source, store):
    mo.stop(provider is None)
    _clipboard = provider.value == CLIPBOARD
    _level = ai.send_level()  # kt.config : schema, summary (pseudonyms) or clear
    if _clipboard and _level == "clear":
        _level = "summary"  # "clear" is for a local model : a chat is outside
    # the pseudonyms of this table, kept for the whole conversation (and between the
    # copy of a prompt and the paste of its answer)
    anon = anonymize.for_table(backend, source.value, hide=_level != "clear")
    with mo.status.spinner("Reading the columns..."):
        description = ai.describe(store[source.value], anon, _level)
    history = []  # what was said, for the next question (a new table starts over)
    _sent = {
        "schema": "the name and type of the columns",
        "summary": "the columns, figures on them and a few rows, with the "
        "customers, people and products renamed (`Customer 12`)",
        "clear": "the columns, figures on them and a few rows, **in clear**",
    }[_level]
    if _clipboard:
        _to = "The prompt you copy to your chat holds"
    elif not available[provider.value].leaves_machine:
        _to = "Nothing leaves this machine : the local model gets"
    else:
        _to = f"{available[provider.value].label} gets"
    mo.accordion(
        {
            "What the model is told": mo.md(
                f"{_to} {_sent}, the columns of the tables to join, your question "
                "and the query of the editor. Its query runs here, on the rows you "
                f"may read.\n\n```\n{description}\n```"
            )
        }
    )
    return anon, description, history


@app.cell
def _(
    CLIPBOARD,
    anon,
    ask_button,
    available,
    derived_kpiten,
    backend,
    derived_tables,
    description,
    get_lang,
    get_mode,
    get_py,
    get_sql,
    history,
    joins,
    mo,
    provider,
    question,
    rewrite_button,
    set_answer,
    set_clip,
    set_py,
    set_sql,
    source,
    store,
    user_id,
):
    # a question, or « rewrite in commented steps » (the query of the editor)
    _rewrite = rewrite_button is not None and rewrite_button.value
    mo.stop(not _rewrite and (not ask_button.value or not question.value.strip()))
    _mode = "steps" if _rewrite else get_mode()
    _lang = get_lang()
    _current = (get_py if _lang == "polars" else get_sql)()
    _set_code = set_py if _lang == "polars" else set_sql
    _question = (
        derived_kpiten.ai.rewrite(backend.get_user_lang(user_id), _lang)
        if _rewrite
        else question.value.strip()
    )
    _all = {**store, **derived_tables}
    _system = derived_kpiten.ai.system_prompt(
        source.value,
        description,
        {name: derived_kpiten.ai.columns(_all[name]) for name in joins.value},
        mode=_mode,
        language=_lang,
    )
    if provider.value == CLIPBOARD:
        # the prompt to copy : the answer comes back by a paste (cells below)
        _content = derived_kpiten.ai.message(_question, _current, anon)
        set_clip(
            {
                "prompt": derived_kpiten.ai.clipboard(_system, _content),
                "first": True,
                "mode": _mode,
                "language": _lang,
            }
        )
    else:
        with mo.status.spinner("The AI writes the query..."):
            _answer = derived_kpiten.ai.ask(
                available[provider.value],
                {**_all, "d": store[source.value]},
                _system,
                _question,
                current=_current,
                history=history,
                anon=anon,
                mode=_mode,
                language=_lang,
            )
        history.extend(_answer.exchange)
        del history[:-8]
        set_answer(_answer)
        if _answer.sql and not _answer.unknown:
            _set_code(_answer.sql)
    return


@app.cell
def _(get_clip, mo):
    # copy the prompt to a chat, paste its answer back
    _clip = get_clip()
    mo.stop(_clip is None)
    paste = mo.ui.text_area(
        placeholder="Paste here the whole answer of the chat",
        full_width=True,
        rows=5,
    )
    use_button = mo.ui.run_button(label="Use the answer")
    _how = (
        "Copy this prompt into a **new conversation** of your chat"
        if _clip["first"]
        else "The query did not run : copy this into the **same conversation**"
    )
    mo.vstack(
        [
            mo.md(f"**1.** {_how} : the copy icon at the top right of the block"),
            mo.ui.code_editor(
                value=_clip["prompt"],
                language="markdown",
                disabled=True,
                max_height=180,
            ),
            mo.md("**2.** Paste its whole answer :"),
            mo.hstack([paste, use_button], align="end", widths=[5, 1]),
        ]
    )
    return paste, use_button


@app.cell
def _(
    anon,
    derived_kpiten,
    derived_tables,
    get_clip,
    mo,
    paste,
    set_answer,
    set_clip,
    set_py,
    set_sql,
    source,
    store,
    use_button,
):
    mo.stop(not use_button.value or not paste.value.strip())
    # the pasted answer : revealed, checked and run like the answer of the api
    _answer = derived_kpiten.ai.receive(
        paste.value,
        {**store, **derived_tables, "d": store[source.value]},
        anon,
        get_clip()["mode"],
        get_clip()["language"],
    )
    _lang = get_clip()["language"]
    set_answer(_answer)
    if _answer.sql and not _answer.unknown:
        (set_py if _lang == "polars" else set_sql)(_answer.sql)
    if _answer.error and _answer.sql and not _answer.unknown:
        # the error, to paste in the same conversation
        set_clip(
            {
                "prompt": derived_kpiten.ai.correction(_answer.error, anon, _lang),
                "first": False,
                "mode": get_clip()["mode"],
                "language": _lang,
            }
        )
    else:
        set_clip(None)
    return


@app.cell
def _(
    derived_kpiten,
    get_answer,
    get_lang,
    get_mode,
    get_py,
    get_sql,
    manager,
    mo,
    set_py,
    set_sql,
):
    _polars = get_lang() == "polars"
    _answer = get_answer()
    _said = []
    if _answer is not None and _answer.text:
        _said.append(mo.callout(mo.md(_answer.text), kind="neutral"))
    if _answer is not None and _answer.error and _answer.sql:
        _said.append(
            mo.callout(
                mo.md(
                    "The query of the AI does not run : "
                    f"`{derived_kpiten.short_error(_answer.error, columns=False)}`"
                ),
                kind="warn",
            )
        )
    editor = mo.ui.code_editor(
        value=(get_py if _polars else get_sql)(),
        language="python" if _polars else "sql",
        min_height=260,
        label=f"The {'polars code' if _polars else 'SQL'} (run when you leave the editor)",
        on_change=set_py if _polars else set_sql,
    )
    # the detail (the SQL and the measures of each step) : a KpiTen manager only
    detail = (
        mo.ui.checkbox(label="Detail") if manager and get_mode() == "steps" else None
    )
    mo.vstack([*_said, editor, *([detail] if detail is not None else [])])
    return detail, editor


@app.cell
def _(
    db,
    derived_kpiten,
    derived_tables,
    detail,
    editor,
    get_lang,
    get_mode,
    mo,
    provider,
    set_mode,
    source,
    store,
    ui,
):
    _detail = bool(detail is not None and detail.value)
    # the table chosen is `d` ; the others, and the derived tables, by their name
    _tables = {**store, **derived_tables, "d": store[source.value]}
    rewrite_button = understand_button = None
    _lang = get_lang()
    try:
        if get_mode() == "query":
            # the result : polars runs the query lazily, optimized ; its first rows
            with mo.status.spinner("Running the query..."):
                _table = derived_kpiten.ai.run(editor.value, _tables, language=_lang)
            _rows = derived_kpiten.ai.PREVIEW_ROWS
            # a global of the cell : marimo sends its clicks only then
            understand_button = mo.ui.button(
                label="🪜 Understand it step by step",
                on_click=lambda _: set_mode("steps"),
            )
            _out = mo.vstack(
                [
                    mo.md(
                        f"**{_table.height:,}** rows".replace(",", "\u202f")
                        + (
                            f" <small>(the first {_rows:,})</small>".replace(
                                ",", "\u202f"
                            )
                            if _table.height == _rows
                            else ""
                        )
                    ),
                    mo.ui.dataframe(ui.plain(_table), page_size=15),
                    mo.hstack(
                        [
                            understand_button,
                            mo.accordion(
                                {
                                    "::lucide:code:: The code to copy (polars)": (
                                        mo.ui.code_editor(
                                            value=derived_kpiten.polars_code(
                                                editor.value, source.value, db, _lang
                                            ),
                                            language="python",
                                            disabled=True,
                                        )
                                    )
                                }
                            ),
                        ],
                        justify="start",
                        align="start",
                        widths=[1, 3],
                    ),
                ]
            )
        else:
            with mo.status.spinner("Running the steps..."):
                _results = derived_kpiten.trace(
                    derived_kpiten.ai.split_code(editor.value, _lang),
                    _tables,
                    detail=_detail,
                )
            # the AI rewrites the query in steps with their words (a query cut by
            # its clauses has none)
            rewrite_button = (
                mo.ui.run_button(label="✨ Rewrite in commented steps")
                if provider is not None
                else None
            )
            _out = mo.vstack(
                [
                    mo.Html(derived_kpiten.render(_results, detail=_detail)),
                    *([rewrite_button] if rewrite_button is not None else []),
                ]
            )
    except Exception as err:
        _out = mo.callout(
            mo.md(
                "The query does not run : "
                f"`{derived_kpiten.short_error(err, columns=False)}`"
            ),
            kind="danger",
        )
    _out
    return rewrite_button, understand_button


@app.cell
def _(get_current, manager, mo):
    # save the query as a derived table : a table of its own, read by its name
    _current = get_current() or {}
    save_name = mo.ui.text(
        value=_current.get("name", ""),
        label="Name",
        placeholder="confirmed_sales",
    )
    save_description = mo.ui.text(
        value=_current.get("description", ""),
        label="Description",
        placeholder="What the table holds",
        full_width=True,
    )
    # every user reads a shared table, each one their own rows : a manager only
    save_shared = (
        mo.ui.checkbox(value=bool(_current.get("shared")), label="Shared")
        if manager
        else None
    )
    save_button = mo.ui.run_button(
        label="::lucide:bookmark-plus:: Save as a derived table"
    )
    mo.vstack(
        [
            mo.md(
                "**Save as a derived table** <small>: other queries (and later the "
                "tiles) read it by its name, on the rows of each user</small>"
            ),
            mo.hstack(
                [
                    save_name,
                    save_description,
                    *([save_shared] if save_shared is not None else []),
                    save_button,
                ],
                align="end",
                justify="start",
            ),
        ]
    )
    return save_button, save_description, save_name, save_shared


@app.cell
def _(
    backend,
    derived_kpiten,
    editor,
    get_lang,
    mo,
    save_button,
    save_description,
    save_name,
    save_shared,
    set_version,
    source,
    user_id,
):
    mo.stop(not save_button.value)
    _name = save_name.value.strip()
    _shared = bool(save_shared is not None and save_shared.value)
    try:
        derived_kpiten.ai.split_code(editor.value, get_lang())  # it parses
        backend.save_derived_table(
            user_id,
            _name,
            editor.value,
            save_description.value.strip(),
            _shared,
            source.value,
            get_lang(),
        )
    except Exception as err:
        _out = mo.callout(mo.md(f"Not saved : {str(err)[:300]}"), kind="danger")
    else:
        # the form keeps what was typed : redrawn, its button would hide this message
        set_version(lambda version: version + 1)
        _out = mo.callout(
            mo.md(f"Saved : a query reads it as `{_name}`."), kind="success"
        )
    _out
    return


@app.cell(hide_code=True)
def _(ui):
    ui.footer()
    return


if __name__ == "__main__":
    app.run()
