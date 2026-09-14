# Nicegui KPIten

NiceGUI port of the (feature-complete) dashboard on the same
`kpiten-core` as shiny-kpiten — SSO, filters, tiles, themes **and**
edit mode.

```bash
cd kpiten/nicegui-kpiten
uv sync
uv run python -m nicegui_kpiten.main        # http://localhost:5001
```

SSO flow (identical to shiny-kpiten/main.py) :
- POST /            {"user_uuid": ...} -> {"session": token}
- GET  /dashboard/auth?session=... -> redirect to /dashboard (nicegui UI)
- tiles for the session user (ACL columns + lang), dev fallback on the
  odoorpc login user.

Run from Odoo : menu KpiTen -> link named `NiceGUI` (ir.config_parameter
`kpiten_services` entry nicegui, pointed to localhost:5001).

Edit mode : switch in the top bar ; tile toolbar (move left/right,
taller/shorter, wider/narrower, delete) + native html5 drag&drop
reorder, auto-saved in Odoo on each action (like the shiny app).

Comparison with the shiny app : see `docs/shiny-vs-nicegui.md`.
