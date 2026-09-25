# kpiten-core

Framework agnostic core library to compute KPI tiles defined in Odoo
(module `kpiten`), used by the Shiny dashboard app (and reusable by
NiceGUI or any other Python UI framework later on).

It provides:

- `Backend` abstraction with a jsonrpc implementation (odoorpc) and a
  stub for the Odoo >= 19 External JSON-2 API.
- `DFStorage`: polars dataframes cached as parquet files with metadata.
- `Df`: dataframe normalization (dates, many2one split, decimals).
- `exec_tile(line, store, predicates)` -> `TileResult`: pure tile
  computation for the kinds `card | graph | pivot | union | data`.
- `filters`: date ranges and dimension predicates/predictions.
- `sandbox`: restricted execution of user polars snippets.

## Usage

```bash
uv sync
uv run pytest -q
```

See `.env.example` for configuration.

## See what a function does (birdseye, snoop)

To understand a function of the core, trace it while its tests run, without touching
the code (dev dependencies `birdseye` and `snoop`) :

```bash
# every expression of every call, in a web page
.venv/bin/python scripts/eye.py kpiten_core.querychat.narrow_store -- tests/test_querychat.py
.venv/bin/python -m birdseye        # http://localhost:7777
# each line run and the values that change, in the terminal
.venv/bin/python scripts/eye.py --snoop kpiten_core.savetile.new_definition -- tests/test_savetile.py
```

Useful on the functions that compute (`querychat`, `savetile`, `dfnorm`, `filters`,
`render.plotly`) ; less on polars in lazy mode (a variable holds a plan, not rows).
