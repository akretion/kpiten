"""Dashboard themes.

A theme is a CSS palette injected at runtime:
- page background (as `linear-gradient` with 3 stops)
- tile surface / borders / accent for titles
- table header fill and text colors (drives the GT styling)

The default theme is `akretion` (matches akretion.com hero gradient) ; a
theme can be chosen in the UI or through the `?theme=` query param.
"""

import polars as pl
from great_tables import GT  # noqa: F401 (annotation)
from kpiten_core.gtable import gt_table


class Theme:
    """Palette + page/tile CSS."""

    def __init__(self, key: str, name: str, palette: dict):
        self.key = key
        self.name = name
        self.palette = palette

    def css(self) -> str:
        p = self.palette
        return f"""
:root {{
  --accent: {p["accent"]};
  --surface: {p["surface"]};
  --text: {p["text"]};
  --border: {p["border"]};
}}
.kpiten-dashboard {{
  color: {p["text"]};
  background: linear-gradient(
    {p["gradient_deg"]}, {p["bg_from"]} 0%, {p["bg_mid"]} 45%, {p["bg_to"]} 130%
  ) fixed;
  min-height: 100vh;
}}
.kpiten-dashboard {{
  --surface-hex: {p["surface_hex"]};
  --thead: {p["thead"]};
  padding: 24px;
}}
/* one compact row : logo, panel, database, theme, actions, freshness */
.top-bar, .filter-bar {{
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
}}
.top-bar .shiny-input-container,
.filter-bar .shiny-input-container {{ margin-bottom: 0; width: auto }}
.top-bar .shiny-html-output:empty {{ display: none }}
.kpiten-dashboard label.control-label {{
  font-size: 11px;
  opacity: .7;
  margin-bottom: 2px;
}}
/* the controls take the colors of the theme (bootstrap ones are white) */
.kpiten-dashboard .form-select,
.kpiten-dashboard .form-control,
.kpiten-dashboard .selectize-input {{
  background-color: color-mix(in srgb, {p["text"]} 8%, transparent);
  color: {p["text"]};
  border: 1px solid {p["border"]};
  border-radius: 6px;
  font-size: 13px;
  min-height: 34px;
  box-shadow: none;
}}
.kpiten-dashboard .form-select {{
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3e%3cpath fill='none' stroke='{p["text"].replace("#", "%23")}' stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='m2 5 6 6 6-6'/%3e%3c/svg%3e");
}}
.kpiten-dashboard .form-select option {{ background: {p["surface_hex"]}; color: {p["text"]} }}
.kpiten-dashboard .selectize-input input {{ color: {p["text"]} }}
.kpiten-dashboard .selectize-control.multi .selectize-input > div {{
  background: {p["thead"]};
  color: {p["text"]};
  border-radius: 4px;
}}
.kpiten-dashboard .selectize-dropdown {{
  background: {p["surface_hex"]};
  color: {p["text"]};
  border: 1px solid {p["border"]};
}}
.kpiten-dashboard .selectize-dropdown .active {{
  background: {p["thead"]};
  color: {p["accent"]};
}}
.kpiten-dashboard .btn-kpiten {{
  background: transparent;
  color: {p["accent"]};
  border: 1px solid {p["accent"]};
  border-radius: 6px;
  font-size: 13px;
  min-height: 34px;
}}
.kpiten-dashboard .btn-kpiten:hover {{
  background: {p["accent"]};
  color: {p["surface_hex"]};
}}
.kpiten-dashboard .form-check-input:checked {{
  background-color: {p["accent"]};
  border-color: {p["accent"]};
}}
.data-freshness {{
  font-size: 11px;
  opacity: 0.55;
  color: {p["text"]};
  align-self: center;
}}
.kpiten-logo {{ height: 80px; width: 80px; align-self: center }}
.framework-side {{ margin-left: auto; align-self: center }}
.framework-logo {{
  width: 76px;
  height: auto;
  border-radius: 6px;
  vertical-align: middle;
}}
.tile-grid {{
  display: grid;
  grid-template-columns: repeat(6, 1fr);  /* see GRID_SPAN in app.py */
  grid-auto-flow: dense;  /* a narrow tile fills the hole a wide one leaves */
  gap: 16px;
}}
/* the tables sit on the left of their tile, like the other front */
.tile .gt_table {{ margin-left: 0 !important; margin-right: 0 !important }}
/* edit mode : the grid item is the wrapper of the tile */
.tile-edit-item {{ display: flex; flex-direction: column }}
.tile-edit-item > .tile {{ flex: 1 }}
.records-link {{
  font-size: 12px;
  margin-top: 6px;
  color: {p["accent"]};
  text-decoration: none;
}}
.records-link::after {{ content: " \\2197"; opacity: .7 }}
.kind-badge {{
  font-size: 10px;
  font-weight: 400;
  color: {p["accent"]};
  border: 1px solid {p["accent"]};
  border-radius: 4px;
  padding: 0 5px;
  margin-left: 8px;
  vertical-align: middle;
  opacity: .8;
}}
/* cards row : odoo-dashboard style kpi line — one compact centered row of
   single-value tiles, each sized to its content */
.card-grid {{
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}}
.card-grid .tile {{
  width: auto;
  min-width: 160px;
  max-width: 280px;
  min-height: 86px !important;  /* grows for a card with a change line */
  height: auto;
  justify-content: center;
  gap: 2px;
}}
.card-grid .tile .kpi-label {{
  font-size: 12px;
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.card-grid .tile .value {{ font-size: 30px; font-weight: 700; line-height: 1.1 }}
.kpi-delta {{ font-size: 12px; font-weight: 600; margin-top: 2px }}
.card-grid .tile .value.kpi-text {{ font-size: 16px; line-height: 1.25; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }}
.kpi-sub {{ font-size: 12px; opacity: .7 }}
.kpi-delta-descr {{ font-weight: 400; opacity: .65 }}
.tile {{
  max-height: 460px;  /* a long table scrolls in its tile */
  background: {p["surface"]};
  color: {p["text"]};
  border: 1px solid {p["border"]};
  border-radius: 12px;
  padding: 8px 12px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 24px rgba(0, 0, 0, .25);
}}
.tile h3 {{
  margin: 0 0 8px 0;
  font-size: 16px;
  font-weight: 600;
  color: {p["accent"]};
}}
.tile .value {{ font-size: 42px; font-weight: 700 }}
/* edit mode */
.tile-grid--edit .tile {{
  border-style: dashed;
  cursor: grab;
}}
.tile-tools {{
  display: flex;
  gap: 4px;
  align-items: center;
  margin-bottom: 6px;
  flex-wrap: wrap;
}}
.tile-tools .tile-id {{
  opacity: .6;
  font-size: 11px;
  margin-right: 4px;
}}
.tile-act {{
  background: {p["thead"]};
  color: {p["text"]};
  border: 1px solid {p["border"]};
  border-radius: 6px;
  padding: 1px 5px;
  cursor: pointer;
  font-size: 11px;
  line-height: 1.4;
}}
.tile-act:hover {{ border-color: {p["accent"]}; color: {p["accent"]} }}
"""


def gt_df(theme: "Theme", df: "polars.DataFrame") -> GT:
    """great_tables table adapted to the theme"""
    return gt_table(df, theme.palette)


AKRETION = Theme(
    "akretion",
    "Akretion",
    {
        "gradient_deg": "135deg",
        "bg_from": "#101226",
        "bg_mid": "#0b1f3b",
        "bg_to": "#0a3f6b",
        "accent": "#00dc82",
        "surface": "rgba(9, 12, 28, .85)",
        "surface_hex": "#0c0f1e",
        "text": "#dbe4ef",
        "border": "rgba(0, 220, 130, .25)",
        "border_hex": "rgba(0,220,130,.25)",
        "thead": "#081225",
        "row_line": "rgba(255,255,255,.06)",
    },
)

MIDNIGHT = Theme(
    "midnight",
    "Midnight",
    {
        "gradient_deg": "160deg",
        "bg_from": "#0e1231",
        "bg_mid": "#142452",
        "bg_to": "#0047e1",
        "accent": "#34cdfe",
        "surface": "rgba(14, 18, 49, .8)",
        "surface_hex": "#0e1231",
        "text": "#e8ecf8",
        "border": "rgba(52, 205, 254, .25)",
        "border_hex": "rgba(52,205,254,.25)",
        "thead": "#0b1030",
        "row_line": "rgba(52,205,254,.12)",
    },
)

LIGHT = Theme(
    "light",
    "Sand",
    {
        "gradient_deg": "180deg",
        "bg_from": "#faf6ef",
        "bg_mid": "#f3ecdd",
        "bg_to": "#e9dfc9",
        "accent": "#a06b2a",
        "surface": "rgba(255, 253, 249, .94)",
        "surface_hex": "#fffdf9",
        "text": "#4a4238",
        "border": "rgba(160, 107, 42, .25)",
        "border_hex": "rgba(160,107,42,.25)",
        "thead": "#f1e9d9",
        "row_line": "rgba(74, 66, 56, .07)",
    },
)

THEMES: dict[str, Theme] = {t.key: t for t in (AKRETION, MIDNIGHT, LIGHT)}
DEFAULT_THEME = "akretion"


def get_theme(key: str) -> Theme:
    return THEMES.get(key or DEFAULT_THEME, THEMES[DEFAULT_THEME])
