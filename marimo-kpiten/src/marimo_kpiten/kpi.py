import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def page_title(mo):
    title_md = mo.md("## KPI • ")
    return (title_md,)


@app.cell
def navigation(mo):
    mo_nav_menu = mo.nav_menu({"/build": "Create", "/kpi": "KPI"})
    return (mo_nav_menu,)


@app.cell
def display_selectors(date_select, layout_select, mo):
    selectors_hstack = mo.hstack(
        [
            mo.vstack([mo.md("Period"), date_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
            mo.vstack([mo.md("Layout"), layout_select.style({"color": "white"})]).style(
                {"max-width": "fit-content", "color": "white"}
            ),
        ],
        justify="start",
    )
    return (selectors_hstack,)


@app.cell(hide_code=True)
def other_deps():
    from great_tables import GT, vals, style, loc
    import polars.selectors as cs

    return loc, style, cs, GT, vals, style


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
    from pathlib import Path
    from marimo_kpiten.services.df_storage import DFStorage
    import json
    import polars as pl

    df_store = DFStorage()

    # using tables in generated
    table_names = []

    no_data_found_callout = None
    try:
        generated = Path("../generated")
        res = generated.iterdir()
        for file in res:
            table_names.append(file.name)
    except FileNotFoundError as FNFE:
        no_data_found_callout = mo.md(
            "There is **no transformations**, nor any **tables** in general to work on. Try to visit `'/'`,"
            + "then `/build` to verify if any tables exist. Then, you can create transformations, "
            + "and they'll be here !"
        ).callout("warn")
    return df_store, json, mo, no_data_found_callout, pl


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
def get_odoo_env():
    """get_odoo_env
    Rend l'env odoo disponible pour toutes les cellules (si il est en paramètre des autres cellules)
    """
    import odoorpc
    from marimo_kpiten.services.env_reader import EnvReader

    env_ = EnvReader()
    odoo = odoorpc.ODOO(env_.get("ODOO_HOST"), port=env_.get("ODOO_PORT"))
    odoo.login(env_.get("ODOO_DB"), env_.get("ODOO_LOGIN"), env_.get("ODOO_PWD"))
    env = odoo.env
    return (env,)


@app.cell
def get_kpiten_config_line_class(env):
    """get_kpiten_config_line_class
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    kpiten_config_line_class = env["kpiten.config.line"]
    return (kpiten_config_line_class,)


@app.cell
def layout_selection(mo):
    layout_options = ["Serial (default)", "2 columns when possible"]
    layout_select = mo.ui.multiselect(
        options=layout_options,
        max_selections=1,
        value=["Serial (default)"],
    )
    return (layout_select,)


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
    return (date_select,)


@app.cell
def compute_date_predicate(date_select, mo, pl):
    mo.stop(not date_select.value)
    from datetime import timedelta, datetime

    date_predicates: list[bool] = []
    time_column = (
        "create_date"  # create_date happens to have distinct values, better for testing
    )
    match date_select.value[0]:
        case "today only":
            date_predicates.append(pl.col(time_column) >= datetime.now())
        case "last week":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=7)
            )
        case "last 30 days":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=30)
            )
        case "last 90 days":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=90)
            )
        case "last 6 months":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=31 * 6)
            )
        case "last year":
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=365)
            )
        case _:
            date_predicates.append(
                pl.col(time_column) >= datetime.now() - timedelta(days=30)
            )
    return (date_predicates,)


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
def load_kpiten_line(kpiten_config_line_class, mo, no_data_found_callout):
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
        line_ids = kpiten_config_line_class.search(
            [("config_id", "=", kpiten_config_line_class.get_conf_id(meta["table"]))]
        )
        for l_id in line_ids:

            def delete_this_transformation(arg):
                kpiten_config_line_class.browse(l_id).unlink()
                mo.output.append(
                    mo.md(
                        "✅ Successfully **deleted** record. **Refresh the page** to see the effect"
                    )
                )

            transformations.append(
                {
                    "config_id": kpiten_config_line_class.browse(l_id).config_id.id,
                    "content": kpiten_config_line_class.browse(l_id).definition,
                    "kind": kpiten_config_line_class.browse(l_id).kind,
                    "delete_this": delete_this_transformation,
                }
            )

        dwt_d = {"df_meta": meta, "transformations": transformations}

        df_wt_list.append(dwt_d)
    return (df_wt_list,)


@app.cell
def compute_kpiten_line(
    df_store, df_wt_list, full_predicates, json, mo, pl, cs, GT, vals, style, loc
):
    """
    compute_kpiten_line
    ---
    - Crée des éléments Marimo d'édition de code Python (mo.ui.code_editor)
    - Récupère les noms de variables impliquées dans les transformations (df, df_next)
    - Retourne les infos créées plus la dataframe pour que exec_kpiten_line/n'importe quelle autre cellule puisse l'utiliser
    """
    mo.stop((not df_wt_list) or (len(df_wt_list) < 1))

    from marimo_kpiten.services.dataframe_util import Df

    exec_context_list = []
    for df_wt in df_wt_list:
        for transform in df_wt["transformations"]:
            used_df = df_wt["df_meta"]["df"]
            used_df_label = df_wt["df_meta"]["table"]
            del_action = transform["delete_this"]
            editor = None

            if transform["kind"] == "data":
                # this process is only relevant for kind=data
                first_line = transform["content"].partition("\n")[0]
                df_like = first_line.split(" ")[2]
                df_next_like = first_line.split(" ")[0]
                editor = mo.ui.code_editor(transform["content"])
                delete_button = mo.ui.button(
                    kind="danger", label="Suppr.", on_click=del_action
                )
                exec_context_list.append(
                    {
                        "context_type": "data",
                        "df": used_df.filter(full_predicates),
                        "label": used_df_label,
                        "editor": editor,
                        "df_like": df_like,
                        "df_next_like": df_next_like,
                        "delete_button": delete_button,
                    }
                )
            elif transform["kind"] == "ban":
                BAN_json = json.loads(transform["content"])
                try:
                    result_df = used_df.filter(full_predicates).sql(
                        BAN_json["BAN_query"]
                    )
                    BAN = result_df.to_dict()[BAN_json["column_alias"]]
                    if len(BAN) > 0:
                        BAN = BAN[0]
                    else:
                        mo.stop(True),
                    exec_context_list.append(
                        {
                            "context_type": "ban",
                            "label": BAN_json["BAN_name"],
                            "BAN": BAN,
                        }
                    )
                except pl.exceptions.ColumnNotFoundError as CNFE:
                    print(
                        f"Could not load BAN {BAN_json['BAN_name']}. Please check",
                        " your spelling, and whether you have the rights to query",
                    )
                    print(f"full error :\n{CNFE}")
            elif transform["kind"] == "union":
                from marimo_kpiten.services.temp_transform_engine import TransformEngine

                union_json = json.loads(transform["content"])
                base_model_df = df_store.retrieve_df(
                    union_json["definition"]["model"]["name"]
                )["df"].filter(
                    pl.col("department_id").is_not_null(),
                    pl.col("budget_type").is_not_null(),
                )
                union_model_df = df_store.retrieve_df(
                    union_json["definition"]["union_model"]["name"]
                )["df"]

                engine = TransformEngine(
                    {"model": "account.analytic.line", "df": base_model_df},
                    {"model": "mrp.workcenter.productivity", "df": union_model_df},
                    "./services/mixed_timesheets.rules.toml",
                )

                engine.run()

                union_model_df = union_model_df.with_columns(
                    pl.lit("production").alias("description")
                )

                bmdf_columns = union_json["definition"]["model"]["columns"]
                umdf_columns = union_json["definition"]["union_model"]["columns"]
                base_model_df = base_model_df.select(bmdf_columns.keys())
                union_model_df = union_model_df.select(umdf_columns.keys())

                base_model_df = base_model_df.rename(bmdf_columns)
                union_model_df = union_model_df.rename(umdf_columns)

                union_model_df.with_columns(
                    pl.when(pl.col("dept").is_null())
                    .then(pl.lit("Production & Méthode / Production"))
                    .otherwise(pl.col("dept"))
                )

                UNION_DF = pl.concat(
                    [base_model_df, union_model_df], how="vertical_relaxed"
                )

                # --- Renaming (stays: these values are used in group_by/filter later, not just display) ---
                UNION_DF = UNION_DF.with_columns(
                    pl.when(pl.col("employé") == "employee")
                    .then(pl.lit("Employé entreprise"))
                    .when(pl.col("employé") == "temporary")
                    .then(pl.lit("Intérimaire"))
                    .when(pl.col("employé").is_null())
                    .then(pl.lit("Employé entreprise"))
                    .when(pl.col("employé") == "contractor")
                    .then(pl.lit("Sous-Traitant / Sous Contrat"))
                    .otherwise(pl.col("employé"))
                    .alias("employé")
                )

                UNION_DF = UNION_DF.with_columns(
                    pl.when(
                        (pl.col("dept") == "production")
                        | (pl.col("dept") == "quality")
                        | (pl.col("dept") == "availability")
                        | (pl.col("dept") == "performance")
                        | (pl.col("dept") == "productive")
                    )
                    .then(pl.lit("Production & Méthode / Production"))
                    .otherwise(pl.col("dept"))
                    .alias("dept")
                )

                UNION_DF = UNION_DF.with_columns(
                    pl.when(pl.col("budget") == "production")
                    .then(pl.lit("FAB"))
                    .when(pl.col("budget") == "installation")
                    .then(pl.lit("POSE"))
                    .when(pl.col("budget") == "service")
                    .then(pl.lit("BE"))
                    .otherwise(pl.col("budget"))
                    .alias("budget")
                )

                # --- Month pivot + aggregation (real computation, stays) ---
                UNION_DF = UNION_DF.with_columns(
                    pl.col("date").dt.month().alias("mois")
                )

                UNION_DF = UNION_DF.pivot(
                    "mois",
                    index=["budget", "dept", "projet", "employé"],
                    values="heures",
                    aggregate_function="sum",
                )

                month_map = {
                    "1": "Janvier",
                    "2": "Février",
                    "3": "Mars",
                    "4": "Avril",
                    "5": "Mai",
                    "6": "Juin",
                    "12": "Décembre",
                }
                present_months = [m for m in month_map if m in UNION_DF.columns]

                UNION_DF = UNION_DF.group_by(["budget", "dept", "employé"]).agg(
                    [pl.col(m).sum() for m in present_months]
                )
                UNION_DF = UNION_DF.rename({m: month_map[m] for m in present_months})
                month_labels = [month_map[m] for m in present_months]

                # --- Filtering + dept collapsing (real logic, stays) ---
                UNION_DF = UNION_DF.filter(
                    (pl.col("dept").str.starts_with("Production"))
                    | (pl.col("dept").str.starts_with("Pose"))
                    | (pl.col("dept").str.starts_with("Projet"))
                    | (pl.col("dept").str.starts_with("Travaux"))
                    | (pl.col("dept").str.starts_with("Bureau"))
                )

                UNION_DF = UNION_DF.with_columns(
                    pl.when(pl.col("dept").str.starts_with("Production"))
                    .then(pl.lit("Production & Méthode"))
                    .otherwise(pl.col("dept"))
                    .alias("dept")
                )

                # --- Final aggregation + sort (no more "can't sort because totals are rows" problem) ---
                final_df = (
                    UNION_DF.group_by(["budget", "dept", "employé"])
                    .agg([pl.col(m).sum() for m in month_labels])
                    .sort(["budget", "dept", "employé"], nulls_last=True)
                )
                final_df = final_df.with_columns(
                    pl.sum_horizontal(month_labels).alias("Heures Totales").round(0)
                ).sort(["budget", "Heures Totales"], descending=[False, True])

                # --- Presentation: replaces grand_total, partition loop, and rounding entirely ---
                gt_table = (
                    GT(final_df, rowname_col="employé", groupname_col="budget")
                    .tab_header(union_json["definition"]["label"])
                    .fmt_number(columns=month_labels, decimals=0)
                    .summary_rows(
                        fns={"TOTAL": [pl.col(m).sum() for m in month_labels]},
                        fmt=lambda x: vals.fmt_number(x, decimals=0),
                    )
                    .grand_summary_rows(
                        fns={"TOTAL GÉNÉRAL": [pl.col(m).sum() for m in month_labels]},
                        fmt=lambda x: vals.fmt_number(x, decimals=0),
                    )
                    .tab_style(
                        style=style.fill(color="lightblue"), locations=loc.summary()
                    )
                    .tab_style(
                        style=style.fill(color="cyan"), locations=loc.grand_summary()
                    )
                    .tab_options(data_row_padding=2)
                )
                exec_context_list.append(
                    {
                        "label": union_json["definition"]["label"],
                        "context_type": "union",
                        "union_df": gt_table,
                    }
                )

            else:
                import plotly.express as px

                graph_json = json.loads(transform["content"])
                CX = graph_json["x"]
                CY = graph_json["y"]
                X_AGG = CX["aggregation"]
                Y_AGG = CY["aggregation"]

                source = None
                fig = None

                # ALTAIR
                # if type(CX) == dict:
                #     CX = alt.X(f"{CX['name']}:{ENCODING_DICT[CX['type']]}", sort="-y")

                # if type(CY) == dict:
                #     CY = alt.Y(f"{CY['name']}:{ENCODING_DICT[CY['type']]}")

                source = (
                    df_store.retrieve_df(graph_json["from"])["df"]
                    .limit(500)
                    .filter(full_predicates)
                )

                match X_AGG:
                    case "sum":
                        source = source.group_by(graph_json["y"]["name"]).agg(
                            pl.col(graph_json["x"]["name"]).sum()
                        )
                    case "count":
                        source = source.group_by(graph_json["y"]["name"]).agg(
                            pl.col(graph_json["x"]["name"]).count()
                        )
                    case _:
                        source = source

                match Y_AGG:
                    case "sum":
                        source = source = source.group_by(graph_json["x"]["name"]).agg(
                            pl.col(graph_json["y"]["name"]).sum()
                        )
                    case "count":
                        source = source.group_by(graph_json["x"]["name"]).agg(
                            pl.col(graph_json["y"]["name"]).count()
                        )
                    case _:
                        source = source

                # source = source.to_pandas()
                x_label = CX["name"].replace("_", " ").capitalize()
                y_label = CY["name"].replace("_", " ").capitalize()
                labels = {
                    CX["name"]: x_label,
                    CY["name"]: y_label,
                }

                match graph_json["graph_type"]:
                    case "bar":
                        fig = px.bar(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                        )
                    case "point":
                        fig = px.scatter(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                        )
                    case "area":
                        fig = px.area(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                        )
                    case _:
                        fig = px.bar(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                        )
                fig.update_layout(
                    autosize=True,
                    margin=dict(l=20, r=20, t=40, b=20),
                )
                label = graph_json["label"]
                graph = mo.ui.plotly(figure=fig)
                delete_button = mo.ui.button(
                    kind="danger", label="Suppr.", on_click=del_action
                )
                exec_context_list.append(
                    {
                        "context_type": "graph",
                        "label": label,
                        "graph": graph,
                        "delete_button": delete_button,
                    }
                )
    return (exec_context_list,)


@app.cell
def exec_kpiten_lines(exec_context_list, layout_select, mo, pl):
    """
    exec_kpiten_lines
    ---
    Affiche les transformation récupérées depuis Odoo
    """
    mo.stop(not exec_context_list)
    mo.stop(len(exec_context_list) < 1)

    ordered = {}
    to_display = []
    selected_layout = layout_select.value[0]
    data_t_width = "80vw" if selected_layout == "Serial (default)" else "40vw"

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
                    scope = {
                        ctx["df_like"]: ctx["df"],
                        "pl": pl,
                        "delete_button": ctx["delete_button"],
                    }
                    exec(ctx["editor"].value, scope)
                    table_html = mo.ui.table(scope[ctx["df_next_like"]].limit(20))
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
                case _:
                    scope = {ctx["df_like"]: ctx["df"], "pl": pl}
                    exec(ctx["editor"].value, scope)
                    fallback_html = mo.ui.table(scope[ctx["df_next_like"]]).text
                    sub_parts_html += f"<div>{fallback_html}</div>"

        to_display.append(sub_parts_html)

    if selected_layout == "Serial (default)":
        inner = "".join(
            [
                f'<div style="display:flex; flex-flow:column; width:100%; gap:1rem">{block}</div>'
                for block in to_display
            ]
        )
        final_html = f'<div style="display:flex; flex-flow:column; width:100%; gap:2rem">{inner}</div>'
    else:
        inner = "".join(
            [
                f'<div style="display:flex; flex-flow:row wrap; gap:1rem; width:200%">{block}</div>'
                for block in to_display
            ]
        )
        final_html = f'<div style="display:flex; flex-flow:column; width:100%; gap:2rem">{inner}</div>'

    mo.Html(final_html)
    return


if __name__ == "__main__":
    app.run()
