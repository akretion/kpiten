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
.filter-bar {{ display: flex; gap: 10px; align-items: end }}
.filter-bar .shiny-input-container {{ margin-bottom: 6px }}
.filter-bar input,
.filter-bar .selectize-input {{ color: {p["text"]} }}
.freshness-bar {{ margin: -6px 0 8px 12px }}
.data-freshness {{
  font-size: 11px;
  opacity: 0.55;
  color: {p["text"]};
}}
.framework-logo {{
  width: 84px;
  height: auto;
  border-radius: 6px;
  vertical-align: middle;
}}
.tile-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
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
  min-height: 0 !important;
  height: 86px;
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
.tile {{
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
