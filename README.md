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

## Ask a KPI, or the whole panel, in words (AI)

With an AI model in `bi/.env` (`ANTHROPIC_API_KEY`, or `LOCAL_LLM_MODEL` for a local
model : see `.env.example`), every user can narrow the rows in words : « only the
confirmed orders », « only the product Standing desk oak » (`kpiten_core.querychat`).

- **A tile** (off by default : `kt.config` › New features › « Ask a tile in words ») :
  its ✨ opens a chat on the right ; the model writes a SQL filter on the
  table of the tile, which is computed again. A badge on the tile gives the filter (SQL
  in its tooltip) ; × removes it, the layers icon applies it to the whole panel.
- **The panel** : the ✨ next to its name. The model writes a filter for the tables that
  need one ; the other tables of the panel follow through their many2one (the lines of
  an order follow the order, the orders follow their lines). The badge next to the name
  lists the filters and the tables that followed (tooltip).
- The filters live in the page, for that user, until it is reloaded ; the rights, the
  period and the filters of the panel still apply ; the spreadsheet export and the
  drill-down read the narrowed rows too.
- What the model is told of a table is set in `kt.config` (the columns only, or figures
  and a few rows with pseudonyms, or in clear ; for a panel, no rows) ; `kt.config` › AI
  turns it off.
- A filter is checked before it runs (`sqltile.check_where` : no other table, no file).
