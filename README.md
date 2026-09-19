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
