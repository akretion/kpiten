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
