import marimo
import polars as pl

__generated_with = "0.23.9"
app = marimo.App(width="full")


@app.cell
def page_title(mo):
    title_md = mo.md("## KPI • ")
    return title_md


@app.cell
def navigation(mo):
    from marimo_kpiten.helpers.ui import nav_menu

    mo_nav_menu = nav_menu("/build", "New")
    return mo_nav_menu


@app.cell
def display_selectors(date_select, date_range, layout_select, render_opt_select, mo):
    core = mo.hstack(
        [
            mo.vstack([mo.md("Period"), date_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
            mo.vstack([mo.md("Dates"), date_range]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
        ],
        justify="start",
    ).style({"color-scheme": "dark"})
    opts = mo.hstack(
        [
            mo.vstack([mo.md("Layout"), layout_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
            mo.vstack(
                [mo.md("Display"), render_opt_select.style({"color": "white"})]
            ).style({"max-width": "fit-content", "color": "white"}),
        ],
        justify="start",
    ).style({"color-scheme": "dark"})
    return core, opts


@app.cell
def show_options_toggle(mo):
    show_opts = mo.ui.switch(value=False, label="+")
    return show_opts


@app.cell(hide_code=True)
def other_deps():
    from marimo_kpiten.helpers.compute_cases import (
        card_case,
        dataframe_case,
        graph_case,
        union_case,
        union_old_case,
    )
    from marimo_kpiten.helpers.date import process_dt_predicate
    from marimo_kpiten.helpers.dimension import (
        dimension_options,
        dimension_values,
    )

    return (
        card_case,
        dataframe_case,
        graph_case,
        union_case,
        union_old_case,
        process_dt_predicate,
        dimension_options,
        dimension_values,
    )


@app.cell
def display_headers(
    core,
    dash_select,
    dim_col,
    dim_vals,
    mo,
    mo_nav_menu,
    opts,
    show_opts,
    title_md,
):
    dash_ui = mo.vstack([mo.md("Dashboard"), dash_select]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    dim_ui = mo.vstack(
        [mo.md("Dimension"), mo.hstack([dim_col, dim_vals])]
    ).style({"max-width": "fit-content", "color": "white"})
    opt_items = [opts] if show_opts.value else []
    mo.hstack(
        [
            mo.hstack([title_md, core, dash_ui, dim_ui, *opt_items]),
            mo.hstack([show_opts, mo_nav_menu]).style({"color-scheme": "dark"}),
        ],
        justify="start",
    )
    return


@app.cell
def _():
    import marimo as mo
    from marimo_kpiten.services.df_storage import DFStorage

    df_store = DFStorage()

    # using tables in parquet
    table_names = df_store.list_table_names()

    no_data_found_callout = None
    if not table_names:
        no_data_found_callout = mo.md(
            "There is **no transformations**, nor any **tables** in general to work on. Try to visit `'/'`,"
            + "then `/build` to verify if any tables exist. Then, you can create transformations, "
            + "and they'll be here !"
        ).callout("warn")
    return df_store, mo, no_data_found_callout


@app.cell
def app_style():
    from marimo_kpiten.helpers.ui import style_html

    style_html()
    return


@app.cell
def fallback_page(exec_context_list, mo):
    mo.stop(len(exec_context_list) >= 1)
    mo.md(
        "## That's where your transformations will be\n"
        "> Make transformations via the `build` page, then go right back here."
    )
    return


@app.cell
def no_data_found(mo, no_data_found_callout):
    from marimo_kpiten.helpers.ui import no_data

    no_data(mo, no_data_found_callout)
    return


@app.cell
def _get_config_model():
    """
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    from marimo_kpiten.common import _get_config_model

    config_model = _get_config_model()
    return config_model


@app.cell
def layout_selection(mo):
    from marimo_kpiten.helpers.ui import select as _select

    layout_select = _select(["Serial", "2 columns when possible"], ["Serial"])
    return layout_select


@app.cell
def render_engine_selection(mo):
    from marimo_kpiten.helpers.ui import select as _select

    render_opt_select = _select(["Reporting", "Exploration"], ["Exploration"])
    return render_opt_select


@app.cell
def date_state(mo):
    from marimo_kpiten.helpers.date import bounds_for_option

    period, set_period = mo.state(["last year"])
    daterange, set_daterange = mo.state(bounds_for_option("last year"))

    return period, set_period, daterange, set_daterange, bounds_for_option


@app.cell
def period_select_widget(bounds_for_option, mo, period, set_daterange, set_period):
    from marimo_kpiten.helpers.ui import select as _select

    date_options = [
        "today only",
        "last week",
        "last 30 days",
        "last 90 days",
        "last 6 months",
        "last 1 year",
        "last 5 years",
        "last year",
    ]

    def on_period_change(sel):
        set_period(sel)
        if sel:
            bounds = bounds_for_option(sel[0])
            if bounds:
                set_daterange(bounds)

    date_select = _select(date_options, period(), on_change=on_period_change)

    return date_select


@app.cell
def date_range_widget(mo, daterange, set_daterange, set_period):
    def on_range_change(val):
        if val:
            set_daterange(val)
            set_period([])

    date_range = mo.ui.date_range(value=daterange(), on_change=on_range_change)

    return date_range


@app.cell
def compute_date_predicate(daterange, mo, process_dt_predicate):
    mo.stop(not daterange())
    date_predicates = process_dt_predicate(daterange())
    return date_predicates


@app.cell
def dim_options(df_store, dimension_options):
    dfs = [meta["df"] for meta in df_store.retrieve_all_dfs()]
    dim_cols = dimension_options(dfs)
    return dim_cols


@app.cell
def dim_col_widget(dim_cols, mo):
    from marimo_kpiten.helpers.ui import select as _select

    dim_col = _select(dim_cols)
    return dim_col


@app.cell
def dim_vals_widget(df_store, dim_col, dimension_values, mo):
    col = dim_col.value[0] if dim_col.value else None
    vals = (
        dimension_values(
            [meta["df"] for meta in df_store.retrieve_all_dfs()], col
        )
        if col
        else []
    )
    dim_vals = mo.ui.multiselect(options=vals)
    return dim_vals


@app.cell
def dim_predicates(dim_col, dim_vals, pl):
    dim_predicates = []
    if dim_col.value and dim_vals.value:
        dim_predicates = [pl.col(dim_col.value[0]).is_in(dim_vals.value)]
    return dim_predicates


@app.cell
def full_predicates(date_predicates: list[pl.Expr], dim_predicates):
    full_predicates = [*date_predicates, *dim_predicates]
    return (full_predicates,)


@app.cell
def display_cards(exec_context_list, full_predicates, mo):
    mo.stop(exec_context_list == [])
    mo.stop(len(full_predicates) < 1)
    cards = [
        mo.stat(label=card_ctx["label"], value=card_ctx["value"], bordered=True)
        for card_ctx in exec_context_list
        if card_ctx["context_type"] == "card"
    ]
    mo.hstack(cards, wrap=True)
    return


@app.cell
def reload_state(mo):
    reload, set_reload = mo.state(0)
    return reload, set_reload


@app.cell
def dashboard_select(mo):
    from marimo_kpiten.common import _get_dashboard_model
    from marimo_kpiten.helpers.ui import select as _select
    from marimo_kpiten.services.config import load_dashboards

    dash_name_to_id = {}
    dashboards = []
    try:
        dashboards = load_dashboards(_get_dashboard_model())
        dash_name_to_id = {d["name"]: d["id"] for d in dashboards}
    except Exception:
        pass
    dash_select = _select(
        [d["name"] for d in dashboards],
        value=[dashboards[0]["name"]] if dashboards else None,
    )

    return dash_select, dash_name_to_id


@app.cell
def load_kpiten_line(
    config_model,
    dash_name_to_id,
    dash_select,
    mo,
    no_data_found_callout,
    reload,
    set_reload,
):
    """
    load_kpiten_line
    ---
    - Récupère les transformations de kpiten.config.line via odoorpc et la table qui leur correspond
    """
    mo.stop(no_data_found_callout)
    from marimo_kpiten.services.config import current_user_id, delete_line, load_lines
    from marimo_kpiten.services.df_storage import DFStorage as dfsv

    current_uid = current_user_id()
    dashboard_id = (
        dash_name_to_id.get(dash_select.value[0]) if dash_select.value else None
    )
    df_wt_list = []
    for meta in dfsv.retrieve_all_dfs():
        transformations = []
        for line in load_lines(config_model, meta["table"], dashboard_id):

            def delete_this_transformation(
                arg, line_id=line["id"], set_reload=set_reload
            ):
                delete_line(config_model, line_id)
                set_reload(reload + 1)

            owned = str(line["user_id"]) == current_uid
            transformations.append(
                {**line, "delete_this": delete_this_transformation if owned else None}
            )

        df_wt_list.append({"df_meta": meta, "transformations": transformations})
    return (df_wt_list,)


@app.cell
def compute_kpiten_line(
    df_wt_list,
    full_predicates,
    mo,
    card_case,
    dataframe_case,
    graph_case,
    union_case,
    union_old_case,
):
    """
    compute_kpiten_line
    ---
    - Crée des éléments Marimo d'édition de code Python (mo.ui.code_editor)
    - Récupère les noms de variables impliquées dans les transformations (df, df_next)
    - Retourne les infos créées plus la dataframe pour que exec_kpiten_line/n'importe quelle autre cellule puisse l'utiliser
    """
    mo.stop((not df_wt_list) or (len(df_wt_list) < 1))

    exec_context_list = []
    for df_wt in df_wt_list:
        for transform in df_wt["transformations"]:
            used_df = df_wt["df_meta"]["df"]

            if transform["kind"] == "data":
                dataframe_case(
                    used_df, df_wt, transform, exec_context_list, full_predicates
                )
            elif transform["kind"] == "card":
                card_case(
                    used_df=used_df,
                    transform=transform,
                    exec_context_list=exec_context_list,
                    full_predicates=full_predicates,
                )
            elif transform["kind"] == "union":
                union_case(
                    transform=transform,
                    exec_context_list=exec_context_list,
                    full_predicates=full_predicates,
                )
            elif transform["kind"] == "union_old":
                union_old_case(
                    transform=transform,
                    exec_context_list=exec_context_list,
                    full_predicates=full_predicates,
                )
            else:
                graph_case(
                    transform=transform,
                    full_predicates=full_predicates,
                    exec_context_list=exec_context_list,
                )
    return (exec_context_list,)


@app.cell
def exec_kpiten_lines(exec_context_list, layout_select, render_opt_select, mo):
    """
    exec_kpiten_lines
    ---
    Affiche les transformation récupérées depuis Odoo
    """
    mo.stop(not exec_context_list)
    mo.stop(len(exec_context_list) < 1)

    from marimo_kpiten.helpers.display import (
        data_block,
        graph_block,
        layout_blocks,
        union_block,
        union_old_block,
    )

    selected_layout = layout_select.value[0]
    data_t_width = "80vw" if selected_layout == "Serial" else "40vw"

    ordered = {}
    for c in exec_context_list:
        if c["context_type"] != "card":
            ordered.setdefault(c["label"], []).append(c)

    groups = []
    for ctxs in ordered.values():
        ctx_blocks = []
        for ctx in ctxs:
            match ctx["context_type"]:
                case "data":
                    ctx_blocks.append(
                        data_block(ctx, data_t_width, render_opt_select.value[0], mo)
                    )
                case "union":
                    ctx_blocks.append(union_block(ctx, mo))
                case "union_old":
                    ctx_blocks.append(union_old_block(ctx, mo))
                case "graph":
                    ctx_blocks.append(graph_block(ctx, mo))
        groups.append(mo.vstack(ctx_blocks, gap="0.5rem"))

    layout_blocks(groups, selected_layout, mo)
    return


if __name__ == "__main__":
    app.run()
