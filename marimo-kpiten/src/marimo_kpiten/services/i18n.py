from marimo_kpiten.services.RPC import RPC
from marimo_kpiten.services.file_state import FileState

_LANG_CACHE: tuple[str, str] | None = None

_CATALOGS = {
    "en_US": {},
    "fr_FR": {
        "Period": "Période",
        "Layout": "Disposition",
        "Display": "Affichage",
        "Panel": "Panneau",
        "Dimension": "Dimension",
        "New": "Nouveau",
        "KPI": "KPI",
        "Build": "Créer",
        "today only": "aujourd'hui",
        "last week": "7 derniers jours",
        "last 30 days": "30 derniers jours",
        "last 90 days": "90 derniers jours",
        "last 6 months": "6 derniers mois",
        "last 1 year": "1 an",
        "last 5 years": "5 ans",
        "last year": "année dernière",
        "Serial": "Série",
        "2 columns when possible": "2 colonnes si possible",
        "Reporting": "Reporting",
        "Exploration": "Exploration",
        "graph": "graphique",
        "dataframe": "table de données",
        "card": "carte",
        "union": "union",
        "pivot": "pivot",
        "What to build ?": "Que construire ?",
        "Select a model": "Sélectionner un modèle",
        "Create KPIs": "Créer des KPI",
        "No table selected": "Aucune table sélectionnée",
        "Select a table to start building KPIs.": "Sélectionnez une table pour commencer à créer des KPI.",
        "Paste Code": "Coller le code",
        "Save code to Kpiten": "Enregistrer le code dans Kpiten",
        "My Kpi": "Mon KPI",
        "Save": "Enregistrer",
        "Create": "Créer",
        "Name": "Nom",
        "Graph type": "Type de graphique",
        "X column": "Colonne X",
        "X aggregation": "Agrégation X",
        "Y column": "Colonne Y",
        "Y aggregation": "Agrégation Y",
        "Graph's name...": "Nom du graphique...",
        "Union name": "Nom de l'union",
        "Pivot's name...": "Nom du pivot...",
        "Rows (index)": "Lignes (index)",
        "Columns": "Colonnes",
        "Measure": "Mesure",
        "Aggregation": "Agrégation",
        "Group dates by month": "Grouper les dates par mois",
        "Base cols": "Colonnes base",
        "Union cols": "Colonnes union",
        "Cols of {table}": "Colonnes de {table}",
        "Table 2 (to make an union with {table})": "Table 2 (pour faire une union avec {table})",
        "Successfully stored dataframe. Visit KPI's **{table}** section to see it !": "Table de données enregistrée. Visitez la section **{table}** dans KPI pour la voir !",
        'Please fill in the "**Paste code**" field with python code from dataframe transformation.': 'Veuillez remplir le champ "**Coller le code**" avec du code python de transformation de table.',
        "An error occured, please try again.": "Une erreur est survenue, veuillez réessayer.",
        "Cols of {table}": "Colonnes de {table}",
        "Table 2 (to make an union with {table})": "Table 2 (pour faire une union avec {table})",
        "Supprimer": "Supprimer",
        "Error": "Erreur",
        "Total {y} by {x}": "Total {y} par {x}",
        "Choose an X and a Y column to see the preview.": "Choisis une colonne X et une colonne Y pour voir l'aperçu.",
        "Choose an index, a column and a measure to see the preview.": "Choisis un index, une colonne et une mesure pour voir l'aperçu.",
        "Successfully stored graph. Visit KPI's **{table}** section to see it !": "Graphique enregistré. Visitez la section **{table}** dans KPI pour le voir !",
        "Couldn't store graph, please try again later.": "Impossible d'enregistrer le graphique, veuillez réessayer plus tard.",
        "Successfully stored card. Visit the **{table}** section in `KPI` to see it !": "Carte enregistrée. Visitez la section **{table}** dans `KPI` pour la voir !",
        "Couldn't store card, please try again later.": "Impossible d'enregistrer la carte, veuillez réessayer plus tard.",
        "Successfully stored union. Visit the **{table}** section in `KPI` to see it !": "Union enregistrée. Visitez la section **{table}** dans `KPI` pour la voir !",
        "Couldn't store union, please try again later.": "Impossible d'enregistrer l'union, veuillez réessayer plus tard.",
        "Successfully stored pivot. Visit KPI's section to see it !": "Pivot enregistré. Visitez la section KPI pour le voir !",
        "Couldn't store pivot, please try again later.": "Impossible d'enregistrer le pivot, veuillez réessayer plus tard.",
        "No data available. Visit '/' then /build to create tables and transformations.": "Aucune donnée disponible. Visitez '/' puis /build pour créer des tables et des transformations.",
        "That's where your transformations will be": "C'est ici que vos transformations seront affichées",
        "Make transformations via the build page, then go right back here.": "Créez des transformations via la page build, puis revenez ici.",
        "There isn't any data to work on. Create a valid 'kpiten.config' record in Odoo.": "Il n'y a aucune donnée sur laquelle travailler. Créez un enregistrement 'kpiten.config' valide dans Odoo.",
        "> You provide an SQL query that generates an interesting number / short information about your company, and the result will be displayed as a KPI Card in the `KPI` section.": "> Vous fournissez une requête SQL qui génère un nombre intéressant / une information courte sur votre entreprise, et le résultat sera affiché comme une carte KPI dans la section `KPI`.",
        "No data found.": "Aucune donnée trouvée.",
    },
}


def _normalize(lang: str | None) -> str:
    if not lang:
        return "en_US"
    base = lang.split("_")[0].lower()
    if base == "fr":
        return "fr_FR"
    return "en_US"


def current_lang() -> str:
    global _LANG_CACHE
    uid = FileState.retrieve_state("user_id") or ""
    if _LANG_CACHE is not None and _LANG_CACHE[0] == uid:
        return _LANG_CACHE[1]
    lang = "en_US"
    try:
        if uid:
            lang = RPC().env["res.users"].browse(int(uid)).lang
    except Exception:
        pass
    _LANG_CACHE = (uid, _normalize(lang))
    return _LANG_CACHE[1]


def set_lang(lang: str):
    global _LANG_CACHE
    _LANG_CACHE = (FileState.retrieve_state("user_id") or "", _normalize(lang))


def t(key: str, **kwargs) -> str:
    catalog = _CATALOGS.get(current_lang(), {})
    value = catalog.get(key, key)
    if kwargs:
        return value.format(**kwargs)
    return value


def tr_options(items: list[str]) -> dict[str, str]:
    return {item: t(item) for item in items}
