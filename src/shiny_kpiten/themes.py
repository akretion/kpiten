"""Dashboard themes.

A theme is a CSS palette injected at runtime ; the palettes are the ones of
`kpiten_core.themes` (shared with NiceGUI) :
- page background (as `linear-gradient` with 3 stops)
- tile surface / borders / shadow / accent for titles
- table header fill and text colors (drives the GT styling)
- optionally the colors of the page around the tiles (`page_text`, `page_accent`,
  `page_border`, `page_surface`) : a dark page with light tiles ; the colors of the
  tiles when not set

The default theme is the one of `kt.config` ; the one a user chooses in the UI is kept
in Odoo (`kt.user.theme`), and a theme can be asked through the `?theme=` query param.
"""

import polars as pl
from great_tables import GT  # noqa: F401 (annotation)
from kpiten_core import themes as core_themes
from kpiten_core.render.gtable import gt_table


class Theme:
    """Palette + page/tile CSS."""

    def __init__(self, key: str, name: str, palette: dict):
        self.key = key
        self.name = name
        self.palette = palette

    def css(self) -> str:
        p = self.palette
        page = {
            key: p.get(f"page_{key}", p[fallback])
            for key, fallback in (
                ("text", "text"),
                ("accent", "accent"),
                ("border", "border"),
                ("surface", "surface_hex"),
            )
        }
        return f"""
:root {{
  --accent: {p["accent"]};
  --surface: {p["surface"]};
  --text: {p["text"]};
  --border: {p["border"]};
}}
.kpiten-dashboard {{
  color: {page["text"]};
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
/* the side bar : the panel, its filters, the theme ; the colors of the page */
.kpiten-layout {{
  background: transparent !important; --_sidebar-bg: transparent;
  min-height: calc(100vh - 48px);  /* the side bar goes down the whole page */
}}
.kpiten-layout > .main {{ background: transparent; padding: 8px 16px 16px }}
.kpiten-sidebar {{
  --_sidebar-fg: {page["text"]};
  --bslib-sidebar-fg: {page["text"]};
  background: color-mix(in srgb, {page["surface"]} 70%, transparent) !important;
  color: {page["text"]} !important;
  border-right: 1px solid {page["border"]} !important;
}}
.kpiten-sidebar label, .kpiten-sidebar .form-check-label, .kpiten-brand {{
  color: {page["text"]} !important;
}}
.kpiten-sidebar .filter-bar {{ display: block }}
.kpiten-sidebar .shiny-input-container {{ width: 100% !important; margin-bottom: 12px }}
.kpiten-sidebar .collapse-toggle {{ color: {page["text"]} }}
.kpiten-brand {{
  display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 18px;
  margin-bottom: 8px;
}}
.kpiten-brand img.kpiten-logo {{ width: 40px; height: 40px }}
.top-bar h2 {{ font-size: 22px; font-weight: 700; margin: 0 8px 0 0; color: {page["text"]} }}
.top-bar {{ align-items: center !important }}
.top-bar .btn-kpiten {{ width: 38px; padding: 0; display: grid; place-items: center }}
.top-bar .btn-kpiten svg {{ width: 15px; height: 15px; fill: currentColor }}
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
  background-color: color-mix(in srgb, {page["text"]} 8%, transparent);
  color: {page["text"]};
  border: 1px solid {page["border"]};
  border-radius: 6px;
  font-size: 13px;
  min-height: 34px;
  box-shadow: none;
}}
.kpiten-dashboard .form-select {{
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3e%3cpath fill='none' stroke='{page["text"].replace("#", "%23")}' stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='m2 5 6 6 6-6'/%3e%3c/svg%3e");
}}
.kpiten-dashboard .form-select option {{ background: {p["surface_hex"]}; color: {p["text"]} }}
.kpiten-dashboard .selectize-input input {{ color: {page["text"]} }}
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
  color: {page["accent"]};
  border: 1px solid {page["accent"]};
  border-radius: 6px;
  font-size: 13px;
  min-height: 34px;
}}
.kpiten-dashboard .btn-kpiten:hover {{
  background: {page["accent"]};
  color: {page["surface"]};
}}
.kpiten-dashboard .form-check-input:checked {{
  background-color: {page["accent"]};
  border-color: {page["accent"]};
}}
.data-freshness {{
  font-size: 11px;
  opacity: 0.55;
  color: {page["text"]};
  align-self: center;
}}
.kpiten-logo {{ height: 80px; width: 80px; align-self: center }}
.app-footer {{
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 20px;
  margin-top: 28px;
  color: {page["text"]};  /* the main area of bslib has its own, dark */
}}
.framework-credit {{
  display: flex;
  align-items: center;
  gap: 8px;
  color: inherit;
  font-size: 13px;
  text-decoration: none;
}}
.framework-credit span {{ opacity: .75 }}
.framework-logo {{ width: 40px; height: 40px; vertical-align: middle }}
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
  min-width: 200px;
  max-width: 280px;
  min-height: 86px !important;  /* grows for a card with a change line */
  height: auto;
  justify-content: center;
  gap: 2px;
  padding: 10px 14px 6px;
}}
/* a card : its badge on the line of its title, its value, a thin trend */
.kpi-head {{ display: flex; align-items: center; gap: 8px; min-width: 0 }}
.badge-icon {{
  width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
  flex: none;
}}
.card-grid .tile .kpi-head .kpi-label {{ text-transform: uppercase; letter-spacing: .04em }}
.kpi-trend {{ height: 34px; margin: 2px -4px 0; overflow: hidden }}
.card-grid .tile .kpi-label {{
  font-size: 12px;
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.card-grid .tile .value {{ font-size: 26px; font-weight: 700; line-height: 1.15 }}
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
  box-shadow: {p.get("shadow", core_themes.DARK_SHADOW)};
}}
.tile h3 {{
  margin: 0 0 8px 0;
  font-size: 15px;
  font-weight: 600;
  color: {p["accent"]};
  display: flex;
  align-items: center;
  gap: 8px;
}}
.tile h3 .tile-icon svg, .tile h3 .tile-actions svg {{
  width: 14px; height: 14px; fill: currentColor;
}}
.tile h3 .tile-actions {{ margin-left: auto; display: flex; gap: 6px; align-items: center }}
.tile h3 .tile-info {{ opacity: .45; cursor: help; color: {p["text"]} }}
.tile-full {{
  background: transparent; border: 0; padding: 2px; color: {p["text"]}; opacity: .45;
  cursor: pointer; line-height: 1;
}}
.tile-full:hover, .tile h3 .tile-info:hover {{ opacity: .9 }}
/* a tile in full screen : over the page, all its rows */
.tile.tile--full {{
  position: fixed; inset: 24px; z-index: 1050; max-height: none !important;
  box-shadow: 0 24px 80px rgba(0, 0, 0, .45);
}}
.tile:not(.tile--full) {{ transition: transform .15s ease, box-shadow .15s ease }}
.tile-grid:not(.tile-grid--edit) .tile:not(.tile--full):hover {{ transform: translateY(-2px) }}
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


THEMES: dict[str, Theme] = {
    key: Theme(key, palette["name"], palette)
    for key, palette in core_themes.PALETTES.items()
}
DEFAULT_THEME = core_themes.DEFAULT


def get_theme(key: str | None) -> Theme:
    """The theme of a key (an old key gives the theme that replaced it), else the
    default one."""
    return THEMES[core_themes.key(key) or DEFAULT_THEME]
