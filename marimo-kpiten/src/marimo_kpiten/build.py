import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


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
def get_json():
    import json

    return (json,)


@app.cell
def navigation(mo):
    build_nav = mo.nav_menu({"/build": "Create", "/kpi": "KPI"})
    return build_nav


@app.cell(hide_code=True)
def _(mo):
    from marimo_kpiten.services.df_storage import DFStorage
    import pathlib

    df_store = DFStorage()

    tables = []
    tname_to_profile_id: dict[str, int] = {}
    no_data_found_callout = None

    try:
        # using tables in generated
        generated = pathlib.Path("../generated/dataframes")
        res = generated.iterdir()
        for file in res:
            tables.append(file.name)
    except FileNotFoundError as FNFE:
        no_data_found_callout = mo.callout(
            "There isn't any data to work on. Try visiting /login !",
            kind="warn",
        )

    df_w_meta = []

    for name in tables:
        table_data = df_store.retrieve_df(
            name
        )  # récupère les tables par noms de dossier dans generated
        if table_data:
            table_name = table_data["table"]
            _df = table_data["df"]

            df_w_meta.append({"name": table_name, "df": _df})
    return df_store, no_data_found_callout, tables


@app.cell
def app_style(mo):
    style_sheet = ""
    with open("../styles/first.css") as f:
        style_sheet = f.read()
    mo.Html(f"""<style>{style_sheet}</style>""")
    return


@app.cell
def no_data_found(mo, no_data_found_callout):
    mo.stop(not no_data_found_callout)
    no_data_found_callout
    return


@app.cell
def display_header(mo: marimo, stn_ui, build_nav):
    mo.hstack(
        [
            mo.hstack([mo.md("## Build • "), stn_ui]).style(
                {"max-width": "fit-content"}
            ),
            mo.hstack([build_nav]).style({"max-width": "fit-content"}),
        ],
        justify="space-between",
    )


@app.cell
def select_df_to_build(mo, tables):
    selected_table_name_label = mo.md("Select a table")
    selected_table_name = mo.ui.multiselect(options=tables, max_selections=1)

    stn_ui = mo.vstack([selected_table_name_label, selected_table_name]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    return (selected_table_name, stn_ui)


@app.cell
def display_selected_table(df_store, mo, selected_table_name):
    page_title = mo.md("# Create KPIs")
    display_title = mo.md("## No table selected")
    build_df = mo.md("> Select a table to start building KPIs.")
    d = None
    if len(selected_table_name.value) >= 1:
        sanitized_tbn = selected_table_name.value[0].replace(".", " ").capitalize()
        df_info = df_store.retrieve_df(selected_table_name.value[0])
        if df_info:
            display_title = mo.md(f"## Build Dataframes with **{sanitized_tbn}**")
            d = df_info["df"]
            build_df = mo.ui.dataframe(d)
    mo.vstack([page_title, display_title, build_df])
    return d, sanitized_tbn


@app.cell
def code_input(d, mo):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Paste code"
    """
    mo.stop(type(d) is type(None))
    python_text = mo.ui.text_area()
    mo.vstack([mo.md("## Paste Code"), python_text]).style({"color": "white"})
    return (python_text,)


@app.cell
def save_code_input(d, mo):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    mo.stop(type(d) is type(None))
    save = mo.ui.run_button(label="Save code to Kpiten")
    save
    return (save,)


@app.cell
def store_df_code(env, mo, python_text, save, selected_table_name):
    """
    store_df_code
    ---
    Stocke la transformation de dataframe via odoorpc.
    """
    mo.stop(
        not python_text.value or not save.value or len(selected_table_name.value) < 1
    )
    storedf_message = f"Successfully stored dataframe. Visit KPI's **{selected_table_name.value[0]}** section to see it !"
    storedf_kind = "success"
    if not python_text.value or python_text.value == "":
        storedf_message = f'Please fill in the "**Paste code**" field with python code from dataframe transformation.'
        storedf_kind = "warn"
    record = env["kpiten.config.line"].create_conf_line(
        selected_table_name.value[0], python_text.value, "data"
    )
    if not record:
        storedf_message = f"An error occured, please try again."
        storedf_kind = "error"
    mo.md(storedf_message).callout(kind=storedf_kind)
    return


@app.cell
def build_graph_form(d, mo: marimo, sanitized_tbn):
    mo.stop(type(d) is type(None))

    graph_type_options = ["bar", "point", "area"]
    # column_types = ["quantitative", "temporal", "nominal", "ordinal"]
    aggregation_types = ["none", "count", "sum"]

    type_of_graph_select = mo.ui.multiselect(
        options=graph_type_options, max_selections=1
    )
    name_input = mo.ui.text(placeholder="Graph's name...")
    column_x_select = mo.ui.multiselect(options=d.columns, max_selections=1)
    # column_x_type_select = mo.ui.multiselect(
    #     label="X column specifier", options=column_types, max_selections=1
    # )
    column_x_aggregation = mo.ui.multiselect(
        options=aggregation_types,
        max_selections=1,
        value=["none"],
    )

    column_y_select = mo.ui.multiselect(options=d.columns, max_selections=1)
    # column_y_type_select = mo.ui.multiselect(
    #     label="Y column specifier", options=column_types, max_selections=1
    # )
    column_y_aggregation = mo.ui.multiselect(
        options=aggregation_types,
        max_selections=1,
        value=["none"],
    )

    create_button = mo.ui.run_button(kind="neutral", label="Create")

    form = {
        "label": name_input,
        "graph_type": type_of_graph_select,
        "x": {
            # "type": column_x_type_select,
            "name": column_x_select,
            "aggregation": column_x_aggregation,
        },
        "y": {
            # "type": column_y_type_select,
            "name": column_y_select,
            "aggregation": column_y_aggregation,
        },
    }

    mo.vstack(
        [
            mo.md(f"## Build a Graph from **{sanitized_tbn}**"),
            name_input,
            mo.hstack([mo.md("Graph type"), type_of_graph_select], justify="start"),
            mo.md("### X Axis").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("X Column"), column_x_select]),
                    mo.vstack([mo.md("X Aggregation"), column_x_aggregation]),
                ]
            ),
            mo.md("### Y Axis").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("Y Column"), column_y_select]),
                    mo.vstack([mo.md("Y Aggregation"), column_y_aggregation]),
                ]
            ),
            create_button,
        ]
    ).style({"max-width": "50%", "color": "white"})
    return create_button, form


@app.cell
def save_graph_form_data(
    create_button,
    form,
    json,
    kpiten_config_line_class,
    mo,
    selected_table_name,
):
    mo.stop(not create_button.value)

    form_record = kpiten_config_line_class.create_conf_line(
        selected_table_name.value[0],
        json.dumps(
            {
                "label": form["label"].value,
                "graph_type": form["graph_type"].value[0],
                "from": selected_table_name.value[0],
                "x": {
                    # "type": form["x"]["type"].value[0],
                    "name": form["x"]["name"].value[0],
                    "aggregation": form["x"]["aggregation"].value[0],
                },
                "y": {
                    # "type": form["y"]["type"].value[0],
                    "name": form["y"]["name"].value[0],
                    "aggregation": form["y"]["aggregation"].value[0],
                },
            }
        ),
        "graph",
    )
    message = f"Successfully stored graph. Visit KPI's **{selected_table_name.value[0]}** section to see it !"
    callout_kind = "success"
    if not form_record:
        message = "Couldn't store graph, please try again later."
        callout_kind = "error"

    mo.md(
        message,
    ).callout(kind=callout_kind)
    return


@app.cell
def build_BAN(d, mo, sanitized_tbn):
    # BAN -> Big Ass Number, terme réellement utilisé pour parler des cartes de KPI avec des
    # Chiffres ou des infos dessus.
    mo.stop(type(d) is type(None))
    ban_cell_title = mo.md(f"## Build a BAN (*KPI card*) from **{sanitized_tbn}**")
    ban_cell_desc = mo.md(
        "> You provide an SQL query that generates an interesting number / short "
        "information about your company, and the result will be displayed as a "
        "KPI Card in the `KPI` section."
    )
    BAN_name = mo.ui.text(placeholder="BAN name")
    BAN_col_alias = mo.ui.text(placeholder="alias of column that holds your data")
    BAN_sql = mo.ui.code_editor(placeholder="Your SQL query", language="sql")
    save_BAN_btn = mo.ui.run_button(kind="neutral", label="Save BAN")

    mo.vstack(
        [
            ban_cell_title,
            ban_cell_desc,
            BAN_name,
            BAN_sql,
            mo.hstack([mo.md("BAN alias"), BAN_col_alias], justify="start").style(
                {"color": "white"}
            ),
            save_BAN_btn,
        ]
    )
    return BAN_col_alias, BAN_name, BAN_sql, save_BAN_btn


@app.cell
def save_BAN(
    BAN_col_alias,
    BAN_name,
    BAN_sql,
    json,
    kpiten_config_line_class,
    mo,
    sanitized_tbn,
    save_BAN_btn,
    selected_table_name,
):
    mo.stop(not save_BAN_btn.value)

    BAN_record = kpiten_config_line_class.create_conf_line(
        selected_table_name.value[0],
        json.dumps(
            {
                "BAN_name": BAN_name.value,
                "BAN_query": BAN_sql.value,
                "from": selected_table_name.value[0],
                "column_alias": BAN_col_alias.value,
            }
        ),
        "ban",
    )

    save_BAN_message = f"Successfully stored BAN. Visit the **{sanitized_tbn}** section in `KPI` to see it !"
    save_BAN_kind = "success"
    if not BAN_record:
        save_BAN_message = "Couldn't store BAN, please try again later."
        save_BAN_kind = "error"
    mo.md(save_BAN_message).callout(kind=save_BAN_kind)
    return


if __name__ == "__main__":
    app.run()
