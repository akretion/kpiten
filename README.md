# Shiny KPIten

Interactive dashboard read of the Odoo-held KPI configs, sitting on
`kpiten-core`.

## Run (dev mode)

```bash
cd kpiten/shiny-kpiten
uv sync
uv run python -m uvicorn shiny_kpiten.main:this_app --host 0.0.0.0 --port 5000
```

## Odoo side

The Odoo action `action_redirect_to_kpiten(app="dashboard")` posts a user
uuid to `internal_url/` and redirects to
`external_url/dashboard/auth?session=<token>`.

## Ask a KPI in words (AI)

With an AI model in `bi/.env` (`ANTHROPIC_API_KEY`, or `LOCAL_LLM_MODEL` for a local
model : see `.env.example`), every tile has a ✨ button, for every user. It opens a chat
on the right : « only the confirmed orders », « without the Export team ». The model
writes a SQL filter on the table of the tile (`kpiten_core.querychat`) ; the tile is
computed again on the rows it keeps, a badge on the tile gives its SQL (tooltip) and ×
removes it.

- Only that tile changes, for that user, until the page is reloaded ; the rights, the
  period and the filters of the panel still apply.
- What the model is told of the table is set in `kt.config` (the columns only, or
  figures and a few rows with pseudonyms, or in clear) ; `kt.config` › AI turns it off.
- The filter is checked before it runs (`sqltile.check_where` : no other table, no file).
