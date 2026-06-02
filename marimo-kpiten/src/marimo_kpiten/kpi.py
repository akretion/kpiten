import marimo
import polars
from marimo_kpiten.services.df_file_storage_service import DFStorage
from odoorpc import ODOO

__generated_with = "0.23.4"
app = marimo.App(width="medium")


@app.cell
def navigation(mo):
    mo.nav_menu({"/build": "Create", "/kpi": "KPI"})
    return


@app.cell
def _():
    import marimo as mo
    from pathlib import Path
    from marimo_kpiten.services.df_file_storage_service import DFStorage
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

    # for name in table_names:
    #     if name != "notebook_state":
    #         df_info = df_store.retrieve_df(name)
    #         if df_info:
    #             df_name = df_info["table"]
    #             df_data = df_info["df"]
    #             vs = mo.vstack(
    #                 [
    #                     mo.md(f'# {df_name.replace("_", " ").capitalize()}'),
    #                     mo.md("---"),
    #                     mo.ui.dataframe(df_data),
    #                 ]
    #             )
    return df_store, json, mo, pl, no_data_found_callout


@app.cell
def page_title(mo: marimo):
    mo.md("# KPIs \n> KPIs **you** have created")


@app.cell()
def fallback_page(mo: marimo, exec_context_list):
    mo.stop(len(exec_context_list) >= 1)
    mo.md(
        "## That's where your transformations will be\n"
        "> Make transformations via the `build` page, then go right back here."
    )


@app.cell()
def no_data_found(mo: marimo, no_data_found_callout):
    mo.stop(not no_data_found_callout)
    no_data_found_callout


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
def date_filter(mo: marimo):
    date_options = [
        "today only",
        "last week",
        "last 30 days",
        "last 90 days",
        "last 6 months",
        "last year",
    ]
    date_select = mo.ui.multiselect(
        label="Time period", options=date_options, max_selections=1, value=["last year"]
    )

    date_select
    return date_select


@app.cell
def company_filter(mo: marimo, df_store: DFStorage):
    from marimo_kpiten.services.notebook_state_service import NotebookStateService

    nb_ss = NotebookStateService()
    company_select = None

    build_nbs = nb_ss.retrieve_notebook_state("build")
    if build_nbs:
        selected_table_name = build_nbs["selected_table_name"]

        selected_df = df_store.retrieve_df(selected_table_name)["df"]
        companies = selected_df.select("company_id").to_series().to_list()
        unique_companies = set(companies)

        company_select = mo.ui.multiselect(
            label="Company",
            options=["All", *unique_companies],
            max_selections=1,
            value=["All"],
        )

    company_select  # if an error occurs, it just silently doesn't display since it's None
    return company_select


@app.cell
def compute_date_predicate(mo: marimo, pl: polars, date_select: marimo.ui.multiselect):
    mo.stop(not date_select.value[0])
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
    return date_predicates


@app.cell
def compute_company_predicate(
    mo: marimo,
    pl: polars,
    company_select: marimo.ui.multiselect,
    env: ODOO,
):
    mo.stop(not company_select.value[0])
    company_predicates = []
    company_exists = (
        len(env["res.company"].search([("name", "=", company_select.value[0])])) >= 1
    )
    if company_exists:
        company_predicates.append(pl.col("company_id") == company_select.value[0])
    elif company_select.value[0] == "All":
        company_predicates.append(pl.col("company_id") == pl.col("company_id"))
    return company_predicates


@app.cell
def full_predicates(date_predicates: list[bool], company_predicates: list[bool]):
    full_predicates = [*date_predicates, *company_predicates]
    return full_predicates


@app.cell
def load_kpiten_line(kpiten_config_line_class, mo, no_data_found_callout):
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
    mo.stop(no_data_found_callout)
    from marimo_kpiten.services.df_file_storage_service import DFStorage as dfsv

    all_df_metadata = dfsv.retrieve_all_dfs()
    df_wt_list = []
    for meta in all_df_metadata:
        transformations = []
        line_ids = kpiten_config_line_class.search(
            [("config_id", "=", kpiten_config_line_class.get_conf_id(meta["table"]))]
        )
        for l_id in line_ids:
            transformations.append(
                {
                    "config_id": kpiten_config_line_class.browse(l_id).config_id.id,
                    "content": kpiten_config_line_class.browse(l_id).definition,
                    "kind": kpiten_config_line_class.browse(l_id).kind,
                }
            )

        dwt_d = {"df_meta": meta, "transformations": transformations}

        df_wt_list.append(dwt_d)
    return (df_wt_list,)


@app.cell
def compute_kpiten_line(
    df_store: DFStorage,
    df_wt_list,
    json,
    mo: marimo,
    pl: polars,
    full_predicates: list[bool],
):
    """
    compute_kpiten_line
    ---
    - Crée un élément Marimo d'édition de code Python (mo.ui.code_editor)
    - Récupère les noms de variables impliquées dans les transformations (df, df_next)
    - Retourne les infos créées plus la dataframe pour que exec_kpiten_line/n'importe quelle autre cellule puisse l'utiliser

    TODO
    - maintenir la fonction pour qu'elle puisse gérer ce que `load_kpiten_line` retournera après modifs.
      - elle doit donc faire une boucle sur la donnée itérable envoyée et pour chacune d'entre elle crééer un
      scope valide (donc df_next_like et df_like) qui correspond bien aux données récupérées dans kpiten.config.line
      - renvoyer une structure qui contient les scopes, les dataframes et les editors pour chaque transformations
    """
    mo.stop((not df_wt_list) or (len(df_wt_list) < 1))

    exec_context_list = []
    for df_wt in df_wt_list:
        for transform in df_wt["transformations"]:
            used_df = df_wt["df_meta"]["df"]
            used_df_label = df_wt["df_meta"]["table"]
            editor = None

            if transform["kind"] == "data":
                # these transforms are relevant only for kind=data
                first_line = transform["content"].partition("\n")[0]
                df_like = first_line.split(" ")[2]
                df_next_like = first_line.split(" ")[0]
                editor = mo.ui.code_editor(transform["content"])
                exec_context_list.append(
                    {
                        "context_type": "data",
                        "df": used_df.filter(full_predicates),
                        "label": used_df_label,
                        "editor": editor,
                        "df_like": df_like,
                        "df_next_like": df_next_like,
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
                width = 800
                height = 900

                match graph_json["graph_type"]:
                    case "bar":
                        fig = px.bar(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                            width=width,
                            height=height,
                        )
                    case "point":
                        fig = px.scatter(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                            width=width,
                            height=height,
                        )
                    case "area":
                        fig = px.area(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                            width=width,
                            height=height,
                        )
                    case _:
                        fig = px.bar(
                            source,
                            x=CX["name"],
                            y=CY["name"],
                            labels=labels,
                            width=width,
                            height=height,
                        )
                label = graph_json["label"]
                graph = mo.ui.plotly(figure=fig)
                exec_context_list.append(
                    {"context_type": "graph", "label": label, "graph": graph}
                )
    return (exec_context_list,)


@app.cell
def exec_kpiten_line(exec_context_list, mo, pl: polars):
    """
    exec_kpiten_line
    ---
    Affiche la table avec la transformation récupérée depuis Odoo

    TODO
    - Faire en sorte que cette fonction accepte ce que compute_kpiten_line renvoie, donc :
      - faire une boucle qui fait la même chose qu'en dessous avec les variables d'itérations
      - il faut en plus que cette boucle construise une liste de `scope[df_next_like]` (donc de dataframes)
      - la liste doit être "appelée" à la fin, comme pour tout ce qu'on veut afficher dans marimo ->
      si la liste s'appelle "scope[df]" :

      ```python
      def _():
        ...
        scope[df] # doit être dernier.
      ```
    """
    mo.stop(not exec_context_list)
    mo.stop(len(exec_context_list) < 1)

    ordered = {}
    to_display = []

    for c in exec_context_list:
        ordered[c["label"]] = []

    for c in exec_context_list:
        ordered[c["label"]].append(c)

    for k in ordered.keys():
        sub_transfo_list = []
        sub_transfo_list.append(mo.md(f"# {k}"))
        for ctx in ordered[k]:
            match ctx["context_type"]:
                case "data":
                    scope = {ctx["df_like"]: ctx["df"], "pl": pl}
                    exec(ctx["editor"].value, scope)
                    sub_transfo_list.append(
                        scope[ctx["df_next_like"]],
                    )
                case "graph":
                    graph_ui = mo.vstack([mo.md(f"## {ctx['label']}"), ctx["graph"]])
                    sub_transfo_list.append(graph_ui)
                case _:
                    scope = {ctx["df_like"]: ctx["df"], "pl": pl}
                    exec(ctx["editor"].value, scope)
                    sub_transfo_list.append(
                        scope[ctx["df_next_like"]],
                    )
        to_display.append(sub_transfo_list)
    to_display


if __name__ == "__main__":
    app.run()
