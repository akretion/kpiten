"""The texts the fronts show, in the language of the connected user (`res.users.lang`).

The texts are written in English in the code ; a catalog per language holds their
translation. A text a catalog lacks stays in English (a month `2026-04`, a year : any
text that is not a sentence goes through unchanged).

    tr = translator("fr_FR")
    tr("Panel")                      # 'Panel' -> 'Tableau'
    tr("Tile #{id} deleted", id=3)   # the {names} are filled after the translation
"""

import re
from collections.abc import Callable

DEFAULT = "en"

FR = {
    # the page
    "Not connected": "Non connecté",
    "Open the dashboard from Odoo : menu KpiTen → {front}.": (
        "Ouvrez le tableau de bord depuis Odoo : menu KpiTen → {front}."
    ),
    "Panel": "Tableau",
    "Period": "Période",
    "Theme": "Thème",
    "Database": "Base",
    "Edit": "Modifier",
    "Made with Shiny": "Fait avec Shiny",
    "Put the KPI on a panel to see it.": "Placez le KPI sur un tableau pour le voir.",
    "This KPI is not visible to you.": "Ce KPI ne vous est pas visible.",
    "No data yet : open the dashboard once to sync it.": (
        "Pas encore de données : ouvrez une fois le tableau de bord pour les synchroniser."
    ),
    "Connected to {db} as {name}": "Connecté à {db} en tant que {name}",
    "Built with": "Réalisé avec",
    "Edit this panel : move, resize or delete its tiles (drag and drop, or the "
    "buttons on each tile). The changes are saved in Odoo.": (
        "Modifier ce tableau : déplacer, redimensionner ou supprimer ses tuiles "
        "(glisser-déposer, ou les boutons de chaque tuile). Les changements sont "
        "enregistrés dans Odoo."
    ),
    "Refresh data : sync with Odoo now, to see its latest changes": (
        "Actualiser : synchroniser avec Odoo maintenant, pour voir ses derniers "
        "changements"
    ),
    "Download the rows of an Odoo model as a spreadsheet": (
        "Télécharger les lignes d'un modèle Odoo en tableur"
    ),
    "Download the rows of a model": "Télécharger les lignes d'un modèle",
    "Download as a spreadsheet : the rows of this model you may read, with the "
    "filters of the panel": (
        "Télécharger en tableur : les lignes de ce modèle que vous pouvez lire, avec "
        "les filtres du tableau"
    ),
    "You may not export the rows.": "Vous ne pouvez pas exporter les lignes.",
    "Data as of {stamp} — parquet snapshot time ; ⟳ syncs with Odoo": (
        "Données du {stamp} — heure de l'extraction ; ⟳ synchronise avec Odoo"
    ),
    "Database switched to {db}": "Base changée pour {db}",
    "Data synced with Odoo.": "Données synchronisées avec Odoo.",
    "initial extract": "extraction initiale",
    "update": "mise à jour",
    "{kind} : {model} — {count} records": "{kind} : {model} — {count} enregistrements",
    # the periods (kpiten_core.filters)
    "full range": "toutes les dates",
    "today only": "aujourd'hui",
    "last 7 days": "7 derniers jours",
    "last 30 days": "30 derniers jours",
    "last 90 days": "90 derniers jours",
    "last 180 days": "180 derniers jours",
    "last 365 days": "365 derniers jours",
    "year to date": "depuis le début de l'année",
    "last year": "l'an dernier",
    "last 5 years": "5 dernières années",
    "Period {start} → {end} ({field})": "Période du {start} au {end} ({field})",
    "Tile: {where}": "Tuile : {where}",
    # the tiles
    "card": "carte",
    "graph": "graphique",
    "pivot": "tableau croisé",
    "data": "données",
    "union": "union",
    "Full screen (Esc to leave)": "Plein écran (Échap pour sortir)",
    "Move left": "Vers la gauche",
    "Move right": "Vers la droite",
    "Wider": "Plus large",
    "Narrower": "Plus étroite",
    "Taller": "Plus haute",
    "Shorter": "Moins haute",
    "Delete": "Supprimer",
    "Open these {count} records in Odoo": "Ouvrir ces {count} enregistrements dans Odoo",
    "Open the first {count} of {total} records in Odoo": (
        "Ouvrir les {count} premiers des {total} enregistrements dans Odoo"
    ),
    "The same list of records, in Odoo (with your rights)": (
        "La même liste d'enregistrements, dans Odoo (avec vos droits)"
    ),
    "First {rows} of {total} rows": "{rows} premières lignes sur {total}",
    "Grouped by month": "Regroupé par mois",
    "Top {limit} of {total}": "Les {limit} premiers sur {total}",
    "Top {limit} of {total} (rest in Others)": (
        "Les {limit} premiers sur {total} (le reste dans Autres)"
    ),
    "Latest {points} points": "Les {points} derniers points",
    "since last period": "depuis la période précédente",
    "Previous period{period} : {previous}": "Période précédente{period} : {previous}",
    "Only a KpiTen manager can edit tiles.": (
        "Seul un gestionnaire KpiTen peut modifier les tuiles."
    ),
    "Tile #{id} deleted": "Tuile n°{id} supprimée",
    "Tiles order saved.": "Ordre des tuiles enregistré.",
    "Drill-down failed : {error}": "Le détail a échoué : {error}",
}

CATALOGS: dict[str, dict[str, str]] = {"fr": FR}


def language(lang: str | None) -> str:
    """The catalog of an Odoo language : `fr_FR`, `fr_BE` -> `fr` (a browser's
    `fr-FR,fr;q=0.9` too) ; English when there is none for it."""
    code = re.split(r"[_,;-]", lang or "")[0].strip().lower()
    return code if code in CATALOGS else DEFAULT


def gettext(text: str, lang: str | None = None, **values) -> str:
    """`text` in `lang`, its `{names}` filled with `values`."""
    translated = CATALOGS.get(language(lang), {}).get(text, text)
    return translated.format(**values) if values else translated


def translator(lang: str | None) -> Callable[..., str]:
    """`tr(text, **values)` in `lang`."""

    def tr(text: str, **values) -> str:
        return gettext(text, lang, **values)

    tr.lang = language(lang)
    return tr


english = translator(DEFAULT)
