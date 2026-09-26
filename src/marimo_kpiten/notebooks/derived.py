import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Step by step")


@app.cell
def _():
    import marimo as mo

    from kpiten_core import anonymize
    from kpiten_core.backend import Backend
    from kpiten_core.loaders import user_store
    from marimo_kpiten import ai, ui

    try:
        import derived_kpiten
    except ImportError:  # the plugin is not in the venv of marimo (make apps)
        derived_kpiten = None
    return Backend, ai, anonymize, derived_kpiten, mo, ui, user_store


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
def _(mo, store):
    source = mo.ui.dropdown(
        sorted(store),
        value="sale.order" if "sale.order" in store else sorted(store)[0],
        label="Table `d`",
    )
    mo.hstack(
        [
            source,
            mo.md(
                "<small>The query reads it as `d` ; the other tables by their name "
                'in quotes : `"sale.order.line"`. One step per `WITH` block, its words '
                "in the `--` comment above it.</small>"
            ),
        ],
        justify="start",
        gap=1.5,
    )
    return (source,)


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
    return EXAMPLES, FIRST_ROWS


@app.cell
def _(EXAMPLES, FIRST_ROWS, mo, source):
    # the query of the editor, that the AI may replace ; a new table starts over
    get_sql, set_sql = mo.state(EXAMPLES.get(source.value, FIRST_ROWS))
    get_answer, set_answer = mo.state(None)  # the last answer of the AI
    return get_answer, get_sql, set_answer, set_sql


@app.cell
def _(ai, anonymize, backend, derived_kpiten, mo, source, store):
    # Ask the AI : it writes the query in steps (skill steps.md of derived-kpiten)
    available = ai.providers() if ai.enabled() else {}
    if not available:
        ai_panel = mo.md(
            "<small>No AI here : turned off in the KpiTen configuration, or none "
            "configured (`ANTHROPIC_API_KEY`, `LOCAL_LLM_MODEL` in `.env`).</small>"
        )
        provider = question = ask_button = anon = description = joins = None
    else:
        _level = ai.send_level()  # kt.config : schema, summary (pseudonyms) or clear
        # the pseudonyms of this table, kept for the whole conversation
        anon = anonymize.for_table(backend, source.value, hide=_level != "clear")
        with mo.status.spinner("Reading the columns..."):
            description = ai.describe(store[source.value], anon, _level)
        # the columns of the tables it may join : only those chosen (a small local
        # model reads a short prompt only)
        joins = mo.ui.multiselect(
            [name for name in sorted(store) if name != source.value],
            label="Tables to join",
        )
        provider = mo.ui.dropdown(
            {p.label: key for key, p in available.items()},
            value=next(iter(p.label for p in available.values())),
            label="Model",
        )
        question = mo.ui.text_area(
            placeholder="The confirmed sales of 2025 by month and salesperson, "
            "or : now only the customers of France",
            full_width=True,
            rows=2,
        )
        ask_button = mo.ui.run_button(label="✨ Ask the AI")
        _sent = {
            "schema": "the name and type of the columns",
            "summary": "the columns, figures on them and a few rows, with the "
            "customers, people and products renamed (`Customer 12`)",
            "clear": "the columns, figures on them and a few rows, **in clear**",
        }[_level]
        ai_panel = mo.vstack(
            [
                mo.hstack([question, ask_button], align="end", widths=[5, 1]),
                mo.hstack(
                    [
                        provider,
                        joins,
                        mo.accordion(
                            {
                                "What the model is told": mo.md(
                                    f"The model gets {_sent}, the columns of the tables "
                                    "to join, your question and the query of the "
                                    "editor. Its query runs here, on the rows you may "
                                    f"read.\n\n```\n{description}\n```"
                                )
                            }
                        ),
                    ],
                    justify="start",
                    align="start",
                ),
            ]
        )
    history = []  # what was said, for the next question (a new table starts over)
    ai_panel
    return anon, ask_button, available, description, history, joins, provider, question


@app.cell
def _(
    anon,
    ask_button,
    available,
    derived_kpiten,
    description,
    get_sql,
    history,
    joins,
    mo,
    provider,
    question,
    set_answer,
    set_sql,
    source,
    store,
):
    mo.stop(ask_button is None or not ask_button.value or not question.value.strip())
    _system = derived_kpiten.ai.system_prompt(
        source.value,
        description,
        {name: derived_kpiten.ai.columns(store[name]) for name in joins.value},
    )
    with mo.status.spinner("The AI writes the query..."):
        _answer = derived_kpiten.ai.ask(
            available[provider.value],
            {**store, "d": store[source.value]},
            _system,
            question.value.strip(),
            current=get_sql(),
            history=history,
            anon=anon,
        )
    history.extend(_answer.exchange)
    del history[:-8]
    set_answer(_answer)
    if _answer.sql:
        set_sql(_answer.sql)
    return


@app.cell
def _(get_answer, get_sql, manager, mo, set_sql):
    _answer = get_answer()
    _said = []
    if _answer is not None and _answer.text:
        _said.append(mo.callout(mo.md(_answer.text), kind="neutral"))
    if _answer is not None and _answer.error and _answer.sql:
        _said.append(
            mo.md(f"<small>The AI could not fix its query : `{_answer.error}`</small>")
        )
    editor = mo.ui.code_editor(
        value=get_sql(),
        language="sql",
        min_height=260,
        label="The SQL of the derived table (run when you leave the editor)",
        on_change=set_sql,
    )
    # the detail (the SQL and the measures of each step) : a KpiTen manager only
    detail = mo.ui.checkbox(label="Detail") if manager else None
    mo.vstack([*_said, editor, *([detail] if detail is not None else [])])
    return detail, editor


@app.cell
def _(derived_kpiten, detail, editor, mo, source, store):
    _detail = bool(detail is not None and detail.value)
    # the table chosen is `d` ; the others keep their name
    _tables = {**store, "d": store[source.value]}
    try:
        with mo.status.spinner("Running the steps..."):
            _results = derived_kpiten.trace(
                derived_kpiten.split(editor.value), _tables, detail=_detail
            )
        _out = mo.Html(derived_kpiten.render(_results, detail=_detail))
    except Exception as err:
        _out = mo.callout(mo.md(f"The query does not run : `{err}`"), kind="danger")
    _out
    return


@app.cell(hide_code=True)
def _(ui):
    ui.footer()
    return


if __name__ == "__main__":
    app.run()
