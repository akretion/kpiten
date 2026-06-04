import marimo

# For typing hints
from marimo_kpiten.services.df_file_storage_service import DFStorage
import polars as pl
from odoorpc import ODOO

__generated_with = "0.22.5"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell()
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
    return env


@app.cell()
def get_kpiten_config_line_class(env):
    """get_kpiten_config_line_class
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    kpiten_config_line_class = env["kpiten.config.line"]
    return kpiten_config_line_class


@app.cell()
def navigation(mo: marimo):
    mo.nav_menu({"/build": "Create", "/kpi": "KPI"})


@app.cell(hide_code=True)
def _(mo: marimo, env: ODOO):  # Affiche les tables initiales
    """
    _
    ---
    Affiche la table Initiale Sales Order en utilisant le contenu de ./generated.
    Sales Order est hardcodé car c'est ce que j'ai utilisé pour tester la feature.\n

    SUGGESTIONS / TODO
    ---
    Pour afficher plusieurs tables, il faudrait :
    - en stocker plusieurs (dans ./generated)
    - trouver un moyen de passer l'information des tables stockées à Marimo depuis odoo.py \n
    -> J'ai pensé à un fichier simple qui contient une liste de tables\n
    -> Utiliser une hstack/vstack pour afficher tout ça
    """
    from marimo_kpiten.services.df_file_storage_service import DFStorage
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
            "There isn't any data to work on. Try visiting / and going back here!",
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

    return df_w_meta, tables, df_store, tname_to_profile_id, no_data_found_callout


@app.cell()
def no_data_found(mo: marimo, no_data_found_callout):
    mo.stop(not no_data_found_callout)
    no_data_found_callout


@app.cell()
def select_df_to_build(mo: marimo, tables: list[str]):
    selected_table_name = mo.ui.multiselect(
        options=tables, max_selections=1, label="Select a table"
    )
    selected_table_name
    return selected_table_name


@app.cell()
def display_selected_table(
    mo: marimo, selected_table_name: marimo.ui.multiselect, df_store: DFStorage
):
    from marimo_kpiten.services.file_state import FileState

    nb_ss = FileState()

    page_title = mo.md("# Create KPIs")
    display_title = mo.md("## No table selected")
    build_df = mo.md("> Select a table to start building KPIs.")
    d = None
    if len(selected_table_name.value) >= 1:
        nb_ss.store_state(
            "build", {"selected_table_name": selected_table_name.value[0]}
        )

        sanitized_tbn = selected_table_name.value[0].replace(".", " ").capitalize()
        df_info = df_store.retrieve_df(selected_table_name.value[0])
        if df_info:
            display_title = mo.md(f"## Build Dataframes with **{sanitized_tbn}**")
            d = df_info["df"]
            build_df = mo.ui.dataframe(d)
    mo.vstack([page_title, display_title, build_df])
    return d, sanitized_tbn


@app.cell()
def code_input(mo: marimo, d):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Paste code"
    """
    mo.stop(type(d) is type(None))
    python_text = mo.ui.text_area(label="## Paste code")
    python_text
    return python_text


@app.cell()
def save_code_input(mo: marimo, d):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    mo.stop(type(d) is type(None))
    save = mo.ui.run_button(label="Save code to Kpiten")
    save
    return save


@app.cell()
def store_df_code(
    mo: marimo,
    save,
    python_text,
    env,
    selected_table_name: marimo.ui.multiselect,
):
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


@app.cell()
def build_graph_form(mo: marimo, d: pl.DataFrame, sanitized_tbn: str):
    from polars import DataFrame

    mo.stop(type(d) is type(None))

    graph_type_options = ["bar", "point", "area"]
    # column_types = ["quantitative", "temporal", "nominal", "ordinal"]
    aggregation_types = ["none", "count", "sum"]

    type_of_graph_select = mo.ui.multiselect(
        label="Graph type", options=graph_type_options, max_selections=1
    )
    name_input = mo.ui.text(placeholder="Graph's name...")
    column_x_select = mo.ui.multiselect(
        label="X column", options=d.columns, max_selections=1
    )
    # column_x_type_select = mo.ui.multiselect(
    #     label="X column specifier", options=column_types, max_selections=1
    # )
    column_x_aggregation = mo.ui.multiselect(
        label="X column aggregation",
        options=aggregation_types,
        max_selections=1,
        value=["none"],
    )

    column_y_select = mo.ui.multiselect(
        label="Y column", options=d.columns, max_selections=1
    )
    # column_y_type_select = mo.ui.multiselect(
    #     label="Y column specifier", options=column_types, max_selections=1
    # )
    column_y_aggregation = mo.ui.multiselect(
        label="Y column aggregation",
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
            type_of_graph_select,
            mo.md("### X Axis"),
            mo.hstack([column_x_select, column_x_aggregation]),
            mo.md("### Y Axis"),
            mo.hstack([column_y_select, column_y_aggregation]),
            create_button,
        ]
    ).style({"max-width": "50%"})

    return form, create_button


@app.cell()
def save_graph_form_data(
    mo: marimo,
    form,
    create_button: marimo.ui.run_button,
    kpiten_config_line_class,
    selected_table_name,
):
    mo.stop(not create_button.value)
    import json

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
    ).callout(
        kind=callout_kind,
    )
