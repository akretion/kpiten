# derived-kpiten

Plugin KpiTen : les **tables dérivées**, du SQL en CTE exécuté **pas à pas** sur les données
de l'utilisateur, et expliqué. Spécification : `docs/kpiten-tables-derivees.md` de `bi/`.

```python
from derived_kpiten import render, split, trace

steps = split(sql)                      # une étape par CTE, puis la requête finale
results = trace(steps, tables, detail)  # chaque étape exécutée par kpiten_core.sqltile
html = render(results, detail)          # le même html pour marimo et Shiny
```

- `split` : le commentaire au-dessus d'une CTE (`-- Étape 1 : …`) devient la phrase de
  l'étape ; le type de l'étape (filtre, calcul, jointure, regroupement, tri…) vient du SQL.
- `trace` : lignes en entrée et en sortie, colonnes ajoutées ou retirées, un échantillon.
  Avec `detail` : les lignes retirées par chaque condition du `WHERE`, les lignes avant et
  après chaque jointure (alerte quand elle les multiplie), la taille des groupes.
- Les chiffres viennent de polars, jamais du texte des commentaires.
- **Les droits** : le plugin ne lit jamais le store. Le front lui donne les tables de
  l'utilisateur (`user_store`), déjà limitées à ce qu'il peut lire ; le SQL passe par
  `sqltile.check` (un `SELECT` seul, pas de lecture de fichier).

L'IA (`derived_kpiten.ai`) : `system_prompt` assemble la skill `skills/steps.md` (la forme en
CTE commentées, ce que le SQL de polars sait faire, les pièges des jointures), la description
de `d` (`kpiten_core.anonymize`, au niveau de `kt.config`) et les colonnes des tables à joindre
choisies ; `ask` envoie la question avec la requête actuelle, remet les pseudonymes en clair,
exécute la réponse pas à pas et renvoie une erreur une fois au modèle.

Utilisé par le notebook `derived.py` de `marimo-kpiten` (`make apps` l'installe dans son
venv). Pas encore de hook pour Shiny.

Tests : `uv run pytest` (ou `PYTHONPATH=src ../kpiten-core/.venv/bin/python -m pytest`).
