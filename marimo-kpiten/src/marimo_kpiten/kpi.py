import marimo

__generated_with = "0.23.9"
app = marimo.App(width="full")


@app.cell
def page_title(mo):
    title_md = mo.md("## KPI • ")
    return title_md


@app.cell
def navigation(mo):
    mo_nav_menu = mo.nav_menu({"/build": "New"})
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
        BAN_case,
        dataframe_case,
        graph_case,
        union_case,
    )
    from marimo_kpiten.helpers.date import process_dt_predicate

    return (BAN_case, dataframe_case, graph_case, union_case, process_dt_predicate)


@app.cell
def display_headers(mo, mo_nav_menu, selectors_hstack, title_md):
    mo.hstack(
        [mo.hstack([title_md, selectors_hstack]), mo_nav_menu],
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
def app_style(mo):
    style_sheet = ""
    with open("../styles/first.css") as f:
        style_sheet = f.read()
    mo.Html(f"""<style>{style_sheet}</style>""")
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
    mo.stop(not no_data_found_callout)
    no_data_found_callout
    return


@app.cell
def _get_odoo_env():
    """
    Makes odoo env available for all cells (if in the parameter of other cells)
    """
    from marimo_kpiten.common import _get_odoo_env

    env = _get_odoo_env()
    return env


@app.cell
def _get_config_model(env):
    """
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    from marimo_kpiten.common import _get_config_model

    config_model = _get_config_model(env)
    return config_model


@app.cell
def layout_selection(mo):
    layout_options = ["Serial", "2 columns when possible"]
    layout_select = mo.ui.multiselect(
        options=layout_options,
        max_selections=1,
        value=["Serial"],
    )
    return layout_select


@app.cell
def render_engine_selection(mo):
    render_opt = ["Reporting", "Exploration"]
    render_opt_select = mo.ui.multiselect(
        options=render_opt, max_selections=1, value=["Exploration"]
    )
    return render_opt_select


@app.cell
def date_filter(mo):
    date_options = [
        "today only",
        "last week",
        "last 30 days",
        "last 90 days",
        "last 6 months",
        "last year",
    ]
    date_select = mo.ui.multiselect(
        options=date_options, max_selections=1, value=["last year"]
    )
    return date_select


@app.cell
def compute_date_predicate(date_select, mo, process_dt_predicate):
    mo.stop(not date_select.value)
    date_predicates = process_dt_predicate(date_select)
    return date_predicates


@app.cell
def full_predicates(date_predicates: list[bool]):
    full_predicates = [*date_predicates]
    return (full_predicates,)


@app.cell
def display_ban(exec_context_list, full_predicates, mo):
    mo.stop(exec_context_list == [])
    mo.stop(len(full_predicates) < 1)
    bans = [
        mo.stat(label=ban_ctx["label"], value=ban_ctx["BAN"], bordered=True)
        for ban_ctx in exec_context_list
        if ban_ctx["context_type"] == "ban"
    ]
    mo.hstack(bans, wrap=True)
    return


@app.cell
def load_kpiten_line(config_model, mo, no_data_found_callout):
    """
    load_kpiten_line
    ---
    - Récupères la première ligne dans kpiten.config.line via odoorpc et prend la transformation
    - Retourne la transformation et la table qui lui correspond (ici Sales Order, hardcodé)
    """
    mo.stop(no_data_found_callout)
    from marimo_kpiten.services.df_storage import DFStorage as dfsv

    all_df_metadata = dfsv.retrieve_all_dfs()
    df_wt_list = []
    for meta in all_df_metadata:
        transformations = []
        line_ids = config_model.search(
            [("config_id", "=", config_model.get_conf_id(meta["table"]))]
        )
        for l_id in line_ids:

            def delete_this_transformation(arg):
                config_model.browse(l_id).unlink()
                mo.output.append(
                    mo.md(
                        "✅ Successfully **deleted** record. **Refresh the page** to see the effect"
                    )
                )

            transformations.append(
                {
                    "config_id": config_model.browse(l_id).config_id.id,
                    "content": config_model.browse(l_id).definition,
                    "name": config_model.browse(l_id).name,
                    "kind": config_model.browse(l_id).kind,
                    "delete_this": delete_this_transformation,
                }
            )

        dwt_d = {"df_meta": meta, "transformations": transformations}

        df_wt_list.append(dwt_d)
    return (df_wt_list,)


@app.cell
def compute_kpiten_line(
    df_wt_list, full_predicates, mo, BAN_case, dataframe_case, graph_case, union_case
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
            elif transform["kind"] == "ban":
                BAN_case(
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

    from marimo_kpiten.services.sandbox import run

    ordered = {}
    to_display = []
    selected_layout = layout_select.value[0]
    data_t_width = "80vw" if selected_layout == "Serial" else "40vw"

    for c in exec_context_list:
        if c["context_type"] is not "ban":
            ordered[c["label"]] = []

    for c in exec_context_list:
        if c["context_type"] is not "ban":
            ordered[c["label"]].append(c)

    for k in ordered.keys():
        sub_parts_html = f'<h1 style="width:100%;margin:0.5rem 0">{k}</h1>'
        for ctx in ordered[k]:
            match ctx["context_type"]:
                case "data":
                    try:
                        result_df = run(
                            ctx["editor"].value,
                            ctx["df"],
                            ctx["df_like"],
                            ctx["df_next_like"],
                        )
                    except Exception as e:
                        result_df = None
                    if result_df is None:
                        table_html = mo.md(
                            f"**Error**  {ctx['editor'].value}"
                            # f"**Error**  {ctx['editor'].value}  {e}"
                        ).callout("warn")
                    else:
                        table_html = mo.ui.table(result_df)
                        if render_opt_select.value[0] == "Reporting":
                            table_html = ctx["style_func"](
                                result_df.limit(20)
                            ).as_raw_html()
                            print(table_html)
                    delete_html = ctx["delete_button"].text
                    sub_parts_html += f"""
                        <div style="display:flex; flex-flow:column; width: {data_t_width}; min-width:300px; gap:0.5rem; padding:0.5rem; box-sizing:border-box">
                            <div style="overflow:scroll">{table_html}</div>
                            {delete_html}
                        </div>
                    """
                case "union":
                    sub_parts_html = mo.vstack(
                        [
                            mo.md(f"## {ctx["label"]}").style({"color": "white"}),
                            ctx["union_df"],
                        ]
                    )

                case "graph":
                    graph_html = ctx["graph"].text
                    delete_html = ctx["delete_button"].text
                    sub_parts_html += f"""
                        <div style="display:flex; flex-flow:column; width:80vw; min-width:400px; gap:0.5rem; padding:0.5rem; box-sizing:border-box">
                            <h2 style="margin:0">{ctx['label']}</h2>
                            {graph_html}
                            {delete_html}
                        </div>
                    """
                case "ban":
                    continue

        to_display.append(sub_parts_html)

    common = 'div style="display:flex; flex-flow'
    if selected_layout == "Serial":
        inner = "".join(
            [
                f'<{common}:column; width:100%; gap:1rem">{block}</div>'
                for block in to_display
            ]
        )
        final_html = f'<{common}:column; width:100%; gap:2rem">{inner}</div>'
    else:
        inner = "".join(
            [
                f'<{common}:row wrap; gap:1rem; width:200%">{block}</div>'
                for block in to_display
            ]
        )
        final_html = f'<{common}:column; width:100%; gap:2rem">{inner}</div>'

    mo.Html(final_html)
    return


if __name__ == "__main__":
    app.run()
