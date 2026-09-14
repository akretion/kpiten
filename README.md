# Shiny KPIten

Interactive dashboard read of the Odoo-held KPI configs, sitting on
`kpiten-core`.

## Run (dev mode)

```bash
cd kpiten/shiny-kpiten
uv sync
uv run python src/shiny_kpiten/main.py  # port 5000
```

## Odoo side

The Odoo action `action_redirect_to_kpiten(app="dashboard")` posts a user
uuid to `internal_url/` and redirects to
`external_url/dashboard/auth?session=<token>`.
