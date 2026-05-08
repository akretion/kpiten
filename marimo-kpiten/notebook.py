import marimo
import typing

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
    from services.env_reader import EnvReader

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


@app.cell(hide_code=True)
def _(mo):  # Affiche les tables initiales (ici Sales Order.)
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
    from services.df_file_storage_service import DFStorageService

    print("underscores")
    df_store = DFStorageService()

    tables = ["Sales Order"]
    df_w_meta = []

    for name in tables:
        table_data = df_store.retrieve_df(
            name
        )  # récupère les tables par nom de dossier dans ./generated
        table_name = table_data[1]
        _df = table_data[4]
        profile_id = table_data[0]
        df_w_meta.append({"profile_id": profile_id, "name": table_name, "df": _df})

    result = []

    for d in df_w_meta:
        label = mo.md(f"**{d['name']}**")
        data = mo.ui.dataframe(d["df"])
        pid = d["profile_id"]

        result.append(mo.vstack([pid, label, data]))

    result

    return df_w_meta


@app.cell()
def code_input(mo):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Python Code"
    """
    python_text = mo.ui.text_area(label="Python Code")
    python_text
    return python_text


@app.cell()
def save_code_input(mo):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    save = mo.ui.run_button(label="Save to Kpiten")
    save
    return save


@app.cell()
def load_kpiten_line(kpiten_config_line_class):
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
    from services.df_file_storage_service import DFStorageService as dfsv
    import polars

    print("load_kpiten_line")

    dfs = dfsv()  # to avoid clashes w/ other cells

    code_to_run = None
    df = polars.DataFrame()

    line_ids = kpiten_config_line_class.search([("config_id", "=", 2)])
    if len(line_ids) > 0:
        l_id = line_ids[0]
        code_to_run = kpiten_config_line_class.browse(l_id).definition

        df = dfs.retrieve_df("Sales Order")[4]

    return (code_to_run, df)


@app.cell()
def compute_kpiten_line(mo, code_to_run, df):
    """
    compute_kpiten_line
    ---
    - Crée un élément Marimo d'édition de code Python
    - Récupère les noms de variables impliquées dans les transformations (df, df_next)
    - Retourne les infos créées plus la dataframe pour que exec_kpiten_line/n'importe quelle autre cellule puisse l'utiliser

    TODO
    - maintenir la fonction pour qu'elle puisse gérer ce que `load_kpiten_line` retournera après modifs.
      - elle doit donc faire une boucle sur la donnée itérable envoyée et pour chacune d'entre elle crééer un
      scope valide (donc df_next_like et df_like) qui correspond bien aux données récupérées dans kpiten.config.line
      - renvoyer une structure qui contient les scopes, les dataframes et les editors pour chaque transformations
    """
    print("computer_kpiten_line")
    mo.stop(not code_to_run)
    editor = mo.ui.code_editor(value=code_to_run)
    first_line = code_to_run.partition("\n")[0]
    df_like = first_line.split(" ")[2]  # <hash>df_next
    df_next_like = first_line.split(" ")[0]  # <hash>df

    print("df_like : ", df_like)
    print("df_next_like : ", df_next_like)

    return (editor, df_like, df_next_like, df)


@app.cell
def exec_kpiten_line(mo, editor, df_like, df_next_like, df):
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
    print("exec")
    mo.stop(not editor.value)
    import polars as pl

    scope = {df_like: df, "pl": pl}
    exec(editor.value, scope)
    scope[df_next_like]  # c'est la dataframe construite par le exec()


@app.cell()
def store_df_code(mo, save, python_text, df_w_meta, kpiten_config_line_class):
    """
    store_df_code
    ---
    Stocke la transformation de dataframe via odoorpc.
    """
    mo.stop(not python_text.value or not save.value)

    for meta in df_w_meta:
        print(kpiten_config_line_class)
        record = kpiten_config_line_class.create(
            {"config_id": meta["profile_id"], "definition": python_text.value}
        )
        print(record)
