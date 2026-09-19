# marimo-kpiten

Front marimo de kpiten (`:5002`). Il ne refait pas les dashboards de Shiny et NiceGUI :
marimo sert à explorer et mettre en forme des analyses sur les données de `kpiten-core`,
avec les droits de l'utilisateur connecté (`user_store` : colonnes autorisées + `ir.rule`).

- `POST /` et `GET /dashboard/auth` : SSO depuis Odoo, comme les autres fronts.
- `SsoMiddleware` (`main.py`) : sans session valide, 403 ; sinon il pose
  `{"user_id", "db"}` dans `request.meta`, que le notebook lit avec
  `mo.app_meta().request.meta`. Le navigateur ne peut pas le choisir.
- marimo tourne en mode « run » (`include_code=False`) : le code des notebooks
  (`src/marimo_kpiten/notebooks/`) est le nôtre, l'utilisateur ne l'édite pas.

## Ajouter une analyse

1. Un notebook `notebooks/<clé>.py` (modèle : `purchase.py`) : il lit l'utilisateur dans
   `mo.app_meta().request.meta`, prend ses données dans `user_store(...)` et commence par
   `ui.header("<clé>", user_id, db)`.
2. Une entrée dans `analyses.py` (icône, titre, une phrase) : elle apparaît sur la page
   d'accueil `/dashboard/`, servie par `notebooks/_index.py`.

Un notebook dont le nom commence par `_` n'est pas servi. `ui.odoo_link(label, url)` met
un lien vers Odoo (nouvel onglet, flèche ↗) dans un tableau `mo.ui.table`.

Démarrage : `make start SVC=marimo` (voir `docs/start.md`).

## Data explorer (IA)

`notebooks/explore.py` : l'utilisateur choisit une table parmi celles qu'il peut lire (le store
`user_store`), la prévisualise, puis discute avec une IA (`mo.ui.chat`). Logique dans `ai.py`.

- L'IA répond avec une explication et un extrait **polars** ; `kpiten_core.sandbox` le vérifie
  (pas d'import, de fichier, de SQL ni de fonction hors liste) et l'exécute sur la table de
  l'utilisateur, déjà limitée à ses droits. Une erreur est renvoyée une fois au modèle pour
  qu'il corrige. Une réponse fait au plus 1000 lignes.
- Fournisseurs (dans `bi/.env`, voir `.env.example`) : Claude (`ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`) et un modèle local à API compatible OpenAI (`LOCAL_LLM_MODEL`,
  `LOCAL_LLM_URL`, Ollama par exemple). Seuls ceux qui sont configurés sont proposés ; sans
  aucun, la page l'explique.
- Ce que le modèle reçoit : le nom et le type des colonnes, les valeurs des colonnes qui en ont
  peu (`AI_SEND_VALUES=0` les retire), les questions et les messages d'erreur du code. Jamais une
  ligne de données. Avec le modèle local, rien ne quitte la machine ; la page indique ce qui part.

### Skills (le vocabulaire donné au modèle)

Des fichiers `.md` de `src/marimo_kpiten/skills/` sont ajoutés au prompt du modèle : `polars.md`
(comment écrire le code accepté par le sandbox, avec des exemples) et `purchase.md` (le
vocabulaire des tables d'achat : acheteur = `user_id.name`, fournisseur =
`partner_id.commercial_partner_id.name`, « commandes » = état `purchase` ou `done`...). Un
petit modèle local se trompe surtout sur ce vocabulaire (regrouper par fournisseur quand on
demande l'acheteur) : c'est ce que les skills corrigent.

- L'en-tête `tables: purchase.order, purchase.order.line` limite un skill à ces tables ; sans
  en-tête il vaut pour toutes. La page dit quels skills sont donnés au modèle.
- L'équipe ajoute les siens dans un dossier à part, sans toucher au code :
  `AI_SKILLS_DIR=/chemin/skills` dans `bi/.env` (relu à chaque question... au démarrage de
  marimo). Un skill court, avec des exemples de code, aide plus qu'un long texte.

### Build a KPI (les besoins récurrents, sans IA)

Au-dessus du chat, des listes déroulantes fabriquent un KPI sur la table choisie : mesure et
calcul (somme, moyenne, nombre de lignes...), regroupement, colonnes d'un croisé, date et
période, filtre. `recipes.py` écrit le polars, le sandbox l'exécute (le même chemin que le code
de l'IA), `kpi_view.py` dessine le résultat et `gallery.py` montre en dessous des visuels de ce
qu'on peut construire (la sortie choisie est encadrée).

- Sorties : une carte (avec sa variation sur la période précédente), un classement (top N), une
  courbe par mois / trimestre / année, un tableau par groupe (avec la part du total et le cumul),
  un tableau croisé.
- Mise en relief (Great Tables) : les valeurs qui font au moins X % du total, les X plus grandes,
  celles au-dessus de la moyenne, ou une carte de chaleur.
- Les couleurs (palette des barres, couleur des graphes pleins) et le format des nombres sont ceux
  de `kt.config`. Le polars derrière chaque KPI est affiché.

### Nouvelles fonctions (onglet « New features » de `kt.config`)

Chacune est **décochée par défaut** ; l'admin la coche dans Odoo (KpiTen → Configuration →
« New features »). Sur `big` elles sont cochées.

| case | ce que ça ajoute |
|---|---|
| Alert thresholds | mise en relief rouge des valeurs au-dessus / en dessous d'un seuil, et alerte sous une carte |
| Concentration | « les 3 plus gros font 32 % du total ; 8 groupes font 80 % », et la mise en relief Pareto |
| Outliers | mise en relief des valeurs à plus de X écarts-types de la moyenne |
| Export a KPI as .ods | téléchargement du tableau en OpenDocument (nombres et couleurs conservés) |
| Save a KPI as a tile | un gestionnaire KpiTen enregistre le KPI en tuile `data` d'un panel (dashboards Shiny / NiceGUI) |
| Refine a KPI with the AI | l'IA reçoit le polars du KPI et la demande de changement |
| Open a list of records in Odoo | un KPI qui liste des enregistrements (clé `__id`) ouvre la même liste dans Odoo |

L'ouverture dans Odoo : une action de liste générique par modèle (`kt.get_records_action`, domaine
`[('id','in',active_ids)]`), et le lien `/odoo/action-<id>?active_ids=1,2,3` (500 ids au plus). Odoo
applique les droits de celui qui ouvre le lien.
