import marimo

# For typing hints
from marimo_kpiten.services.df_file_storage_service import DFStorageService
import polars as pl

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
def _(mo: marimo):  # Affiche les tables initiales
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
    from marimo_kpiten.services.df_file_storage_service import DFStorageService
    import pathlib

    df_store = DFStorageService()

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
        )  # récupère les tables par noms de dossier dans doss generated
        if table_data:
            table_name = table_data["table"]
            _df = table_data["df"]
            profile_id = table_data["profile_id"]

            tname_to_profile_id[name] = profile_id
            df_w_meta.append({"profile_id": profile_id, "name": table_name, "df": _df})

    return df_w_meta, tables, df_store, tname_to_profile_id, no_data_found_callout


@app.cell()
def no_data_found(mo: marimo, no_data_found_callout):
    mo.stop(not no_data_found_callout)
    no_data_found_callout


@app.cell()
def select_df_to_build(mo: marimo, tables: list[str]):
    selected_table_name = mo.ui.multiselect(options=tables, max_selections=1)
    selected_table_name
    return selected_table_name


@app.cell()
def display_selected_table(
    mo: marimo, selected_table_name: marimo.ui.multiselect, df_store: DFStorageService
):
    display_title = mo.md("# No table selected")
    build_df = mo.md("> Select a table to start building KPIs.")
    d = None
    if len(selected_table_name.value) >= 1:
        from marimo_kpiten.services.notebook_state_service import NotebookStateService

        nb_ss = NotebookStateService()
        nb_ss.store_notebook_state(
            "build", {"selected_table_name": selected_table_name.value[0]}
        )

        sanitized_tbn = selected_table_name.value[0].replace("_", " ").capitalize()
        df_info = df_store.retrieve_df(selected_table_name.value[0])
        if df_info:
            display_title = mo.md(f"# {sanitized_tbn}")
            d = df_info["df"]
            build_df = mo.ui.dataframe(d)
    mo.vstack([display_title, build_df])
    return d


@app.cell()
def build_graph_form(mo: marimo, d: pl.DataFrame):
    from polars import DataFrame

    mo.stop(type(d) is type(None))

    graph_type_options = ["bar", "point", "area"]
    column_types = ["quantitative", "temporal", "nominal", "ordinal"]
    aggregation_types = ["none", "count", "sum"]

    type_of_graph_select = mo.ui.multiselect(
        label="Graph type", options=graph_type_options, max_selections=1
    )
    name_input = mo.ui.text(placeholder="Graph's name...")
    column_x_select = mo.ui.multiselect(
        label="X column", options=d.columns, max_selections=1
    )
    column_x_type_select = mo.ui.multiselect(
        label="X column specifier", options=column_types, max_selections=1
    )
    column_x_aggregation = mo.ui.multiselect(
        label="X column aggregation",
        options=aggregation_types,
        max_selections=1,
        value=["none"],
    )

    column_y_select = mo.ui.multiselect(
        label="Y column", options=d.columns, max_selections=1
    )
    column_y_type_select = mo.ui.multiselect(
        label="Y column specifier", options=column_types, max_selections=1
    )
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
            "type": column_x_type_select,
            "name": column_x_select,
            "aggregation": column_x_aggregation,
        },
        "y": {
            "type": column_y_type_select,
            "name": column_y_select,
            "aggregation": column_y_aggregation,
        },
    }

    mo.vstack(
        [
            mo.md("## Build a graph"),
            name_input,
            type_of_graph_select,
            mo.md("### X Axis"),
            mo.hstack([column_x_select, column_x_type_select, column_x_aggregation]),
            mo.md("### Y Axis"),
            mo.hstack([column_y_select, column_y_type_select, column_y_aggregation]),
            create_button,
        ]
    ).style({"max-width": "70%"})

    return form, create_button


@app.cell()
def save_graph_form_data(
    mo: marimo,
    form,
    create_button: marimo.ui.run_button,
    kpiten_config_line_class,
    tname_to_profile_id,
    selected_table_name,
):
    mo.stop(not create_button.value)
    import json

    form_record = kpiten_config_line_class.create(
        {
            "kind": "graph",
            "config_id": tname_to_profile_id[selected_table_name.value[0]],
            "definition": json.dumps(
                {
                    "label": form["label"].value,
                    "graph_type": form["graph_type"].value[0],
                    "from": selected_table_name.value[0],
                    "x": {
                        "type": form["x"]["type"].value[0],
                        "name": form["x"]["name"].value[0],
                        "aggregation": form["x"]["aggregation"].value[0],
                    },
                    "y": {
                        "type": form["y"]["type"].value[0],
                        "name": form["y"]["name"].value[0],
                        "aggregation": form["y"]["aggregation"].value[0],
                    },
                }
            ),
        }
    )
    print(form_record)
    mo.md(
        f"Successfully stored graph. Visit KPI's **{selected_table_name.value[0]}** section to see it !",
    ).callout(
        kind="success",
    )


@app.cell()
def code_input(mo: marimo):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Python Code"
    """
    python_text = mo.ui.text_area(label="Python Code")
    python_text
    return python_text


@app.cell()
def save_code_input(mo: marimo):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    save = mo.ui.run_button(label="Save to Kpiten")
    save
    return save


@app.cell()
def load_kpiten_line(kpiten_config_line_class, selected_table_name, mo: marimo):
    """
    load_kpiten_line
    ---
    - Récupères la première ligne dans kpiten.config.line via odoorpc et prend la transformation
    - Retourne la transformation et la table qui lui correspond (ici Sales Order, hardcodé)

    TODO
    - Faire en sorte que la récupération de la ligne ne soit plus hardcodée.
    > Envisageable de récupérer la dernière à chaque fois grâce à odoorpc et de la logique python (e.g plus grand id)
    - Flow pour récupérer toutes les lignes :
      - boucle qui itère sur chaque ids récupérés par le search
      - récupérer l'id de la config et faire une jointure ON config_id pour trouver le nom exact du profil
      - utiliser le nom pour récupérer la DF correspondante avec .retrieve_df
      - retourner un dictionnaire, et s'assurer que les autres fonctionnent gèrent bien le dictionnaire.
    """
    from marimo_kpiten.services.df_file_storage_service import DFStorageService as dfsv
    import polars

    mo.stop(len(selected_table_name.value) < 1)

    print("load_kpiten_line")

    dfs = dfsv()  # to avoid clashes w/ other cells
    d_info = dfs.retrieve_df(selected_table_name.value[0])

    code_to_run = None
    if d_info:
        df = d_info["table"]

    line_ids = kpiten_config_line_class.search(
        [("config_id", "=", d_info["profile_id"])]
    )
    if len(line_ids) > 0:
        l_id = line_ids[-1]
        code_to_run = kpiten_config_line_class.browse(l_id).definition

    return (code_to_run, df)


### NEEDS FIXING AS OF NOW ###

# @app.cell()
# def compute_kpiten_line(mo, code_to_run, df):
#     """
#     compute_kpiten_line
#     ---
#     - Crée un élément Marimo d'édition de code Python (mo.ui.code_editor)
#     - Récupère les noms de variables impliquées dans les transformations (df, df_next)
#     - Retourne les infos créées plus la dataframe pour que exec_kpiten_line/n'importe quelle autre cellule puisse l'utiliser

#     TODO
#     - maintenir la fonction pour qu'elle puisse gérer ce que `load_kpiten_line` retournera après modifs.
#       - elle doit donc faire une boucle sur la donnée itérable envoyée et pour chacune d'entre elle crééer un
#       scope valide (donc df_next_like et df_like) qui correspond bien aux données récupérées dans kpiten.config.line
#       - renvoyer une structure qui contient les scopes, les dataframes et les editors pour chaque transformations
#     """
#     print("computer_kpiten_line")
#     mo.stop(not code_to_run)
#     editor = mo.ui.code_editor(value=code_to_run)
#     first_line = code_to_run.partition("\n")[0]
#     df_like = first_line.split(" ")[2]  # <hash>df_next
#     df_next_like = first_line.split(" ")[0]  # <hash>df

#     print("df_like : ", df_like)
#     print("df_next_like : ", df_next_like)

#     return (editor, df_like, df_next_like, df)


# @app.cell
# def exec_kpiten_line(
#     mo: marimo, editor, df_like, df_next_like, df, selected_table_name
# ):
#     """
#     exec_kpiten_line
#     ---
#     Affiche la table avec la transformation récupérée depuis Odoo

#     TODO
#     - Faire en sorte que cette fonction accepte ce que compute_kpiten_line renvoie, donc :
#       - faire une boucle qui fait la même chose qu'en dessous avec les variables d'itérations
#       - il faut en plus que cette boucle construise une liste de `scope[df_next_like]` (donc de dataframes)
#       - la liste doit être "appelée" à la fin, comme pour tout ce qu'on veut afficher dans marimo ->
#       si la liste s'appelle "scope[df]" :

#       ```python
#       def _():
#         ...
#         scope[df] # doit être dernier.
#       ```
#     """
#     mo.stop(not editor.value)
#     import polars as pl

#     scope = {df_like: df, "pl": pl}
#     exec(editor.value, scope)
#     mo.vstack(
#         [
#             mo.md(f"## Dernière transformation de {selected_table_name.value[0]}"),
#             scope[df_next_like],
#         ]
#     )  # c'est la dataframe construite par le exec()

######


@app.cell()
def store_df_code(
    mo: marimo,
    save,
    python_text,
    kpiten_config_line_class,
    selected_table_name: marimo.ui.multiselect,
    tname_to_profile_id: dict[str, int],
):
    """
    store_df_code
    ---
    Stocke la transformation de dataframe via odoorpc.
    """
    mo.stop(
        not python_text.value or not save.value or len(selected_table_name.value) < 1
    )

    record = kpiten_config_line_class.create(
        {
            "config_id": tname_to_profile_id[selected_table_name.value[0]],
            "definition": python_text.value,
            "kind": "data",
        }
    )
    print(record)
