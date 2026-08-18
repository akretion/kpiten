import marimo
from marimo_kpiten.services.session_handler import SessionHandler
import polars
from marimo_kpiten.services.df_storage import DFStorage

__generated_with = "0.23.9"
app = marimo.App(width="full")


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
            "There isn't any data to work on. "
            + "Create a valid 'kpiten.config' record in Odoo.",
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
def get_kpiten_config_line_class(env):
    """get_kpiten_config_line_class
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    if not env["ir.model"].search([("model", "=", "kpiten.config")]):
        raise Exception(f"Kpiten module not installed in '{odoo.env.db}' db")
    kpiten_config_line_class = env["kpiten.config.line"]
    return (kpiten_config_line_class,)


@app.cell
def display_header(mo: marimo, stn_ui, build_nav, ts_ui):
    mo.hstack(
        [
            mo.hstack([mo.md("## Build • "), stn_ui, ts_ui]).style(
                {"max-width": "fit-content"}
            ),
            mo.hstack([build_nav]).style({"max-width": "fit-content"}),
        ],
        justify="space-between",
    )


@app.cell
def select_transformation_to_make(mo: marimo):
    transformation_selector_label = mo.md("What to build ?")
    transformation_selector = mo.ui.multiselect(
        options=["graph", "dataframe", "card", "union"],
        max_selections=1,
        value=["dataframe"],
    )

    ts_ui = mo.vstack([transformation_selector_label, transformation_selector]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    return (ts_ui, transformation_selector)


@app.cell
def select_df_to_build(mo: marimo, tables):
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
    selected_table_ui = mo.vstack([page_title, display_title, build_df])
    return d, sanitized_tbn


@app.cell
def show_selected_table(mo, transformation_selector, selected_table_ui):
    mo.stop(transformation_selector.value[0] is not "dataframe")
    selected_table_ui


@app.cell
def code_input(d, mo: marimo, transformation_selector):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Paste code"
    """
    mo.stop(transformation_selector.value[0] is not "dataframe")
    mo.stop(type(d) is type(None))
    python_text = mo.ui.text_area()
    mo.vstack([mo.md("## Paste Code").style({"color": "white"}), python_text])
    return (python_text,)


@app.cell
def save_code_input(d, mo, transformation_selector):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    mo.stop(transformation_selector.value[0] is not "dataframe")
    mo.stop(type(d) is type(None))
    save = mo.ui.run_button(label="Save code to Kpiten")
    save
    return (save,)


@app.cell
def store_df_code(
    env, mo, python_text, save, selected_table_name, transformation_selector
):
    """
    store_df_code
    ---
    Stocke la transformation de dataframe via odoorpc.
    """
    mo.stop(transformation_selector.value[0] is not "dataframe")
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
def build_graph_form(d, mo: marimo, sanitized_tbn, transformation_selector):
    mo.stop(transformation_selector.value[0] is not "graph")
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

    from marimo_kpiten.notebooks.build_helpers.graph_form_ui import graph_form_ui

    graph_form_ui(
        sanitized_tbn,
        name_input,
        type_of_graph_select,
        column_x_select,
        column_x_aggregation,
        column_y_select,
        column_y_aggregation,
        create_button,
    )

    return create_button, form


@app.cell
def save_graph_form_data(
    create_button,
    form,
    json,
    kpiten_config_line_class,
    mo,
    selected_table_name,
    transformation_selector,
):
    mo.stop(transformation_selector.value[0] is not "graph")
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
def build_BAN(d, mo, sanitized_tbn, transformation_selector):
    # BAN -> Big Ass Number, terme réellement utilisé pour parler des cartes de KPI avec des
    # Chiffres ou des infos dessus.
    mo.stop(transformation_selector.value[0] is not "card")
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
    transformation_selector,
):
    mo.stop(transformation_selector.value[0] is not "card")
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


@app.cell
def union_tables_selectors(mo: marimo, transformation_selector, tables, sanitized_tbn):
    mo.stop(transformation_selector.value[0] is not "union")

    table2_sel_label = mo.md(f"Table 2 (to make an union with {sanitized_tbn})")
    table2_selector = mo.ui.multiselect(options=tables, max_selections=1)
    mo.hstack([mo.vstack([table2_sel_label, table2_selector])]).style(
        {"color": "white"}
    )

    return (table2_selector,)


@app.cell
def union_columns_selectors(
    mo: marimo,
    transformation_selector,
    table2_selector,
    d: polars.DataFrame,
    df_store: DFStorage,
    sanitized_tbn,
):
    mo.stop(transformation_selector.value[0] is not "union")
    mo.stop(len(table2_selector.value) is 0)
    # TODO Trouver un moyen de gérer l'ordre des colonnes avec moins d'intervention externe
    sduc_label = mo.md(f"Cols of {sanitized_tbn}")
    selected_df_ucols_selector = mo.ui.multiselect(options=d.columns)
    union_df = df_store.retrieve_df(table2_selector.value[0])["df"]
    union_df_cols_selector = mo.ui.multiselect(options=union_df.columns)

    mo.hstack(
        [
            mo.vstack(
                [
                    mo.md(f"Cols of {sanitized_tbn}"),
                    selected_df_ucols_selector,
                ]
            ).style({"color": "white"}),
            mo.vstack(
                [
                    mo.md(f"Cols of {table2_selector.value[0]}"),
                    union_df_cols_selector,
                ]
            ).style({"color": "white"}),
        ]
    )
    return (selected_df_ucols_selector, union_df_cols_selector)


@app.cell
def show_ucolumn_types(
    mo: marimo, selected_df_ucols_selector, union_df_cols_selector, union_df
):
    mo.stop(transformation_selector.value[0] is not "union")
    mo.stop(len(table2_selector.value) is 0)
    mo.stop(
        len(union_df_cols_selector.value) is 0
        or len(selected_df_ucols_selector.value) is 0
    )
    selected_df_ucols_msg = "No col selected."
    ucols_type_msg = "No col selected."
    selected_df_ucols_type = mo.md(selected_df_ucols_msg)
    union_df_cols_type = mo.md(ucols_type_msg)
    save_union_button = mo.ui.run_button(label="Save")

    if selected_df_ucols_selector.value[0] is not None:
        selected_df_ucols_msg = f"type of {selected_df_ucols_selector.value[-1]} : {d.schema[selected_df_ucols_selector.value[-1]]}"

    if union_df_cols_selector.value[0] is not None:
        ucols_type_msg = f"type of {union_df_cols_selector.value[-1]} : {union_df.schema[union_df_cols_selector.value[-1]]}"

    mo.hstack(
        [
            mo.vstack([selected_df_ucols_msg, selected_df_ucols_selector.value]),
            mo.vstack([ucols_type_msg, union_df_cols_selector.value]),
            mo.vstack([save_union_button.style({"color": "white"})]),
        ]
    ).style({"color": "white"})


@app.cell
def save_union(save_union_button, selected_table_name, table2_selector):
    mo.stop(transformation_selector.value[0] is not "union")
    mo.stop(save_union_button.value is None)


@app.cell
def save_union(selected_df_ucols_selector, union_df_cols_selector, save_union_data):
    pass


if __name__ == "__main__":
    app.run()
