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
def display_selectors(date_select, layout_select, render_opt_select, mo):
    selectors_hstack = mo.hstack(
        [
            mo.vstack([mo.md("Period"), date_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
            mo.vstack([mo.md("Layout"), layout_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
            mo.vstack(
                [mo.md("Display"), render_opt_select.style({"color": "white"})]
            ).style({"max-width": "fit-content", "color": "white"}),
        ],
        justify="start",
    )
    return selectors_hstack


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

    return (
        card_case,
        dataframe_case,
        graph_case,
        union_case,
        union_old_case,
        process_dt_predicate,
    )


@app.cell
def period_label(date_select, mo):
    from marimo_kpiten.helpers.date import period_bounds

    mo.stop(not date_select.value)
    bounds = period_bounds(date_select)
    period_md = mo.md("")
    if bounds:
        start, end = bounds
        period_md = mo.md(f"**{start} → {end}**").style(
            {
                "background": "#eef2f6",
                "color": "#1f2937",
                "padding": "0.25rem 0.75rem",
                "border-radius": "1rem",
            }
        )
    return period_md


@app.cell
def display_headers(mo, mo_nav_menu, period_md, selectors_hstack, title_md):
    mo.hstack(
        [
            mo.hstack([title_md, selectors_hstack]),
            mo.hstack([period_md, mo_nav_menu]),
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
def date_filter(mo):
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
    date_select = _select(date_options, ["last year"])
    return date_select


@app.cell
def compute_date_predicate(date_select, mo, process_dt_predicate):
    mo.stop(not date_select.value)
    date_predicates = process_dt_predicate(date_select)
    return date_predicates


@app.cell
def full_predicates(date_predicates: list[pl.Expr]):
    full_predicates = [*date_predicates]
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
def load_kpiten_line(config_model, mo, no_data_found_callout):
    """
    load_kpiten_line
    ---
    - Récupère les transformations de kpiten.config.line via odoorpc et la table qui leur correspond
    """
    mo.stop(no_data_found_callout)
    from marimo_kpiten.services.config import delete_line, load_lines
    from marimo_kpiten.services.df_storage import DFStorage as dfsv

    df_wt_list = []
    for meta in dfsv.retrieve_all_dfs():
        transformations = []
        for line in load_lines(config_model, meta["table"]):

            def delete_this_transformation(arg, line_id=line["id"]):
                delete_line(config_model, line_id)
                mo.output.append(
                    mo.md(
                        "✅ Successfully **deleted** record. **Refresh the page** to see the effect"
                    )
                )

            transformations.append({**line, "delete_this": delete_this_transformation})

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
        layout_html,
        union_block,
        union_old_block,
    )

    selected_layout = layout_select.value[0]
    data_t_width = "80vw" if selected_layout == "Serial" else "40vw"

    ordered = {}
    for c in exec_context_list:
        if c["context_type"] != "card":
            ordered.setdefault(c["label"], []).append(c)

    blocks = []
    for k, ctxs in ordered.items():
        sub_parts_html = f'<h1 style="width:100%;margin:0.5rem 0">{k}</h1>'
        for ctx in ctxs:
            match ctx["context_type"]:
                case "data":
                    sub_parts_html += data_block(
                        ctx, data_t_width, render_opt_select.value[0], mo
                    )
                case "union":
                    sub_parts_html = union_block(ctx, mo)
                case "union_old":
                    sub_parts_html = union_old_block(ctx, mo)
                case "graph":
                    sub_parts_html += graph_block(ctx, mo)

        blocks.append(sub_parts_html)

    mo.Html(layout_html(blocks, selected_layout))
    return


if __name__ == "__main__":
    app.run()
