# kpiten-spec

The syntax of the KPI of KpiTen : the declarative schema of the syntax version 2 (card,
graph, pivot, the display of a data tile) and the validation of a definition (the union
keeps its own syntax).

- `kpiten_spec.spec` : the schema (`CARD`, `GRAPH`, `PIVOT`, `DATA` : keys, types,
  choices, defaults, help), `validate(data, kind, fields)`, the header of a SQL tile
  (`sql_header`, `display`).
- `kpiten_spec.validate` : `validate_toml(text, kind, fields)`,
  `validate_display(definition, display, fields)`, the messages of a definition.

Standard library only (`tomli` before Python 3.11), Python 3.8 and after : the Odoo
module `kpiten` checks the tiles with it on every series (14 to 20) without installing
kpiten-core ; kpiten-core reads the tiles with it (`kpiten_core.spec` re-exports it).

    uv run pytest
