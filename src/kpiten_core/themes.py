"""The palettes of the dashboard themes, shared by the apps (Shiny, NiceGUI).

A palette is a dict :
- the page : `bg_from`, `bg_mid`, `bg_to`, `gradient_deg` (a 3 stops `linear-gradient`)
- the tiles : `surface` (may be translucent), `surface_hex`, `text`, `accent` (titles,
  links), `border`, `thead` and `row_line` (the tables), `shadow`
- optionally the page around the tiles (`page_text`, `page_accent`, `page_border`,
  `page_surface`) : a dark page with light tiles ; the colors of the tiles when not set
- `dark` : whether the page is dark (the controls of the page follow it)
- `colorway` (the bars, the filled graphs) and `good` / `bad` (the change of a card) :
  used when `kt.config` sets no color of its own

The keys are the values of `kt.config.default_theme` and `kt.user.theme` (Odoo).
"""

DARK_SHADOW = "0 4px 24px rgba(0, 0, 0, .25)"

CAPITAINE = {
    "name": "Capitaine",
    "dark": True,
    "gradient_deg": "150deg",
    "bg_from": "#0a1a33",
    "bg_mid": "#10294f",
    "bg_to": "#1f5a9e",
    "accent": "#f5b301",
    "surface": "rgba(8, 20, 42, .86)",
    "surface_hex": "#0a1830",
    "text": "#e6edf7",
    "border": "rgba(245, 179, 1, .28)",
    "border_hex": "rgba(245,179,1,.28)",
    "thead": "#0c1d3a",
    "row_line": "rgba(230,237,247,.08)",
    "shadow": DARK_SHADOW,
    "colorway": ["#f5b301", "#00dc82", "#5aa9f0", "#ff8a65", "#c3a6ff", "#8fd3ff"],
    "good": "#00dc82",
    "bad": "#ff7b72",
}

GRAPHITE = {
    "name": "Graphite",
    "dark": True,
    "gradient_deg": "180deg",
    "bg_from": "#16181c",
    "bg_mid": "#1b1e23",
    "bg_to": "#262a31",
    "accent": "#5fd4c4",
    "surface": "rgba(36, 39, 46, .94)",
    "surface_hex": "#24272e",
    "text": "#e4e6ea",
    "border": "rgba(255, 255, 255, .09)",
    "border_hex": "rgba(255,255,255,.09)",
    "thead": "#1c1f25",
    "row_line": "rgba(255,255,255,.06)",
    "shadow": "0 1px 2px rgba(0, 0, 0, .3)",
    "colorway": ["#5fd4c4", "#8fa8ff", "#f2c14e", "#f28b82", "#b7bcc6", "#c89cf2"],
    "good": "#5fd48a",
    "bad": "#f28b82",
}

SAND = {
    "name": "Sand",
    "dark": False,
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
    "shadow": "0 2px 12px rgba(74, 66, 56, .10)",
}

# the page of Capitaine (dark gradient, its controls), the tiles of Sand
MIXED = {
    **SAND,
    **{k: CAPITAINE[k] for k in ("gradient_deg", "bg_from", "bg_mid", "bg_to")},
    "name": "Mixed",
    "dark": True,
    "shadow": DARK_SHADOW,
    "page_text": CAPITAINE["text"],
    "page_accent": CAPITAINE["accent"],
    "page_border": CAPITAINE["border"],
    "page_surface": CAPITAINE["surface_hex"],
}

# a pastel : tinted tiles rather than white ones, the page does not dazzle
PECHE = {
    "name": "Pêche",
    "dark": False,
    "gradient_deg": "170deg",
    "bg_from": "#f4e9e2",
    "bg_mid": "#efdfd5",
    "bg_to": "#e6d0c3",
    "accent": "#9c4f3a",
    "surface": "rgba(249, 241, 236, .94)",
    "surface_hex": "#f9f1ec",
    "text": "#46352e",
    "border": "rgba(156, 79, 58, .18)",
    "border_hex": "rgba(156,79,58,.18)",
    "thead": "#f1e3da",
    "row_line": "rgba(70,53,46,.08)",
    "shadow": "0 2px 10px rgba(110, 60, 40, .08)",
    "colorway": ["#e0907a", "#6fa9c2", "#e3b85f", "#8fbd8a", "#ad90d0", "#d68fac"],
    "good": "#2e7a4e",
    "bad": "#b23b36",
}

PRUNE = {
    "name": "Prune",
    "dark": False,
    "gradient_deg": "180deg",
    "bg_from": "#f8f8fa",
    "bg_mid": "#f3f3f6",
    "bg_to": "#eae8ee",
    "accent": "#7a4a70",
    "surface": "#ffffff",
    "surface_hex": "#ffffff",
    "text": "#262a33",
    "border": "#e2dde3",
    "border_hex": "#e2dde3",
    "thead": "#f6f1f5",
    "row_line": "#efebee",
    "shadow": "0 1px 3px rgba(38, 42, 51, .08)",
    "colorway": ["#7a4a70", "#00a09d", "#e4a900", "#d15a5a", "#5c7cbe", "#9aa3b2"],
    "good": "#1f8a4c",
    "bad": "#c94a4a",
}

PALETTES: dict[str, dict] = {
    "capitaine": CAPITAINE,
    "graphite": GRAPHITE,
    "mixed": MIXED,
    "light": SAND,
    "peche": PECHE,
    "prune": PRUNE,
}
DEFAULT = "capitaine"
# the keys of the themes that are gone, still stored in a database or a browser
ALIASES = {"akretion": "capitaine", "midnight": "capitaine", "akretion_sand": "mixed"}


def key(name: str | None) -> str | None:
    """The key of a theme (an old key gives the theme that replaced it), None when the
    name is not a theme."""
    name = ALIASES.get(name, name)
    return name if name in PALETTES else None


def gradient(palette: dict) -> str:
    """The background of the page, as css."""
    p = palette
    return (
        f"linear-gradient({p['gradient_deg']}, {p['bg_from']} 0%, "
        f"{p['bg_mid']} 45%, {p['bg_to']} 130%)"
    )
