import marimo

# for type hints
from odoorpc.env import Environment
from typing import TypedDict, Literal
from marimo_kpiten.services.df_file_storage_service import DF_META, DFStorageService
import polars as pl
import json

__generated_with = "0.23.4"
app = marimo.App(width="medium")


class Transformation(TypedDict):
    config_id: int
    content: str
    kind: Literal["graph", "data"]


class DF_WITH_TRANSFORM(TypedDict):
    df_meta: DF_META
    transformations: list[Transformation]


@app.cell()
def navigation(mo: marimo):
    mo.nav_menu({"/build": "Create", "/kpi": "KPI"})


@app.cell
def _():
    import marimo as mo
    from pathlib import Path
    from marimo_kpiten.services.df_file_storage_service import DFStorageService
    import json

    df_store = DFStorageService()

    # using tables in generated
    table_names = []

    generated = Path("../generated")
    res = generated.iterdir()
    for file in res:
        table_names.append(file.name)

    for name in table_names:
        df_info = df_store.retrieve_df(name)
        df_name = df_info["table"]
        df_data = df_info["df"]
        vs = mo.vstack(
            [
                mo.md(f'# {df_name.replace("_", " ").capitalize()}'),
                mo.md("---"),
                mo.ui.dataframe(df_data),
            ]
        )
    return


@app.cell()
def fallback_page(mo: marimo, exec_context_list):
    mo.stop(len(exec_context_list) >= 1)
    mo.md(
        "# That's where your transformations will be\n"
        "> Make transformations via the `build` page, then go right back here."
    )


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
def get_kpiten_config_line_class(env: Environment):
    """get_kpiten_config_line_class
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    kpiten_config_line_class = env["kpiten.config.line"]
    return kpiten_config_line_class


@app.cell()
def load_kpiten_line(kpiten_config_line_class, mo: marimo):
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

    all_df_metadata = dfsv.retrieve_all_dfs()
    df_wt_list = []
    for meta in all_df_metadata:
        transformations = []
        line_ids = kpiten_config_line_class.search(
            [("config_id", "=", meta["profile_id"])]
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

    return df_wt_list


@app.cell()
def compute_kpiten_line(
    mo: marimo,
    json: json,
    df_wt_list: list[DF_WITH_TRANSFORM],
    df_store: DFStorageService,
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
                # these transforms are relevant only for kind=code
                first_line = transform["content"].partition("\n")[0]
                df_like = first_line.split(" ")[2]
                df_next_like = first_line.split(" ")[0]
                editor = mo.ui.code_editor(transform["content"])

                exec_context_list.append(
                    {
                        "context_type": "data",
                        "df": used_df,
                        "label": used_df_label,
                        "editor": editor,
                        "df_like": df_like,
                        "df_next_like": df_next_like,
                    }
                )
            else:
                import altair as alt

                graph_json = json.loads(transform["content"])
                source = (
                    df_store.retrieve_df(graph_json["from"])["df"]
                    .sort(by=graph_json["x"], descending=False)
                    .to_pandas()
                )
                chart = None

                match graph_json["graph_type"]:
                    case "bar":
                        chart = (
                            alt.Chart(source)
                            .mark_bar()
                            .encode(
                                x=alt.X(f"{graph_json["x"]}:T"),
                                y=alt.Y(f"{graph_json["y"]}:Q"),
                            )
                        )
                    case _:
                        chart = (
                            alt.Chart(source)
                            .mark_bar()
                            .encode(x=graph_json["x"], y=graph_json["y"])
                        )
                label = graph_json["label"]
                graph = mo.ui.altair_chart(chart=chart)
                exec_context_list.append(
                    {"context_type": "graph", "label": label, "graph": graph}
                )

    return exec_context_list


class DFExecutionContext(TypedDict):
    context_type: Literal["data"]
    label: str
    df: pl.DataFrame
    df_like: str
    df_next_like: str
    editor: marimo.ui.code_editor


class GraphExecutionContext:
    context_type: Literal["graph"]
    label: str
    graph: marimo.ui.altair_chart


@app.cell
def exec_kpiten_line(
    mo: marimo,
    exec_context_list: list[DFExecutionContext | GraphExecutionContext],
):
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
    mo.stop(not exec_context_list or len(exec_context_list) < 1)
    import polars as pl

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
                    print(
                        "graph case in exec_kpiten_line, it's just a display problem !!"
                    )
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
