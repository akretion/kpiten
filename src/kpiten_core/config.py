"""The settings of `kt.config` (Odoo), as the apps and the core read them.

Odoo sends one dict (`kt.config.get_config_json`) ; an app hands it to `set_config` once
per session. Every accessor has a default : without a record in Odoo, or with an older
kpiten module, nothing changes.

    {"card": {"comparison": True, "good_color": "#00A04A", "bad_color": "#DC6965"},
     "graph": {"layout": {"colorway": [...]}, "fill_color": "#33d17a"},
     "number": {"format": "space_comma", "small_below": 10, "small_decimals": 2,
                "large_decimals": 0},
     "period": {"default": "last 90 days", "fiscal_start_month": 1},
     "ui": {"theme": "capitaine", "table_rows": 20, "colors": "theme"},
     "explore": {"access": "everyone", "max_rows": 500000, "ods_max_rows": 50000},
     "ai": {"enabled": True, "send_values": True},
     "currency": {"symbol": "$", "position": "before"}}
"""

import datetime

from kpiten_core import themes

CONFIG: dict = {}

# key -> (thousands separator, decimal mark)
NUMBER_FORMATS = {
    "space_comma": (" ", ","),  # 1 234,56
    "space_dot": (" ", "."),  # 1 234.56
    "dot_comma": (".", ","),  # 1.234,56
    "comma_dot": (",", "."),  # 1,234.56
}
THEMES = tuple(themes.PALETTES)
EXPLORE_ACCESS = ("nobody", "managers", "everyone")
DEFAULT_PERIOD = "last 90 days"  # the dashboards open on it, like Odoo


def set_config(config: dict | None) -> None:
    """Replace the settings (the dict is shared : it is cleared, then filled)."""
    CONFIG.clear()
    CONFIG.update(config or {})


def _section(name: str) -> dict:
    return CONFIG.get(name) or {}


# ---- graphs
def graph_colorway() -> list[str]:
    """The palette of the bars (`kt.config`), empty when Odoo sets none."""
    return list((_section("graph").get("layout") or {}).get("colorway") or [])


def graph_fill_color() -> str | None:
    """The color of the filled graphs (area), None when Odoo sets none."""
    return _section("graph").get("fill_color") or None


# ---- cards
def comparison_enabled() -> bool:
    """Whether the cards may show their comparison with the previous period ; on when
    Odoo says nothing, so the cards defined with `compare = true` keep it."""
    return bool(_section("card").get("comparison", True))


def card_color(tone: str, default: str | None) -> str | None:
    """The color of a `good` / `bad` comparison (Odoo's scorecard ones by default)."""
    return _section("card").get(f"{tone}_color") or default


# ---- numbers
def number_separators() -> tuple[str | None, str | None]:
    """(thousands, decimal mark) of the chosen format, (None, None) when Odoo did not
    choose one : the caller falls back on the environment."""
    return NUMBER_FORMATS.get(_section("number").get("format"), (None, None))


def quantity_digits(value) -> int:
    """Decimals of a decimal in a table : `large_decimals` (0 : whole), but
    `small_decimals` (2) below `small_below` (10), where they still tell something."""
    number = _section("number")
    if abs(value) < number.get("small_below", 10):
        return number.get("small_decimals", 2)
    return number.get("large_decimals", 0)


# ---- periods
def default_period() -> str:
    """The period a dashboard opens on ; `""` is the full range, `None` (not set) the
    default one."""
    default = _section("period").get("default")
    return DEFAULT_PERIOD if default is None else default


def fiscal_start_month() -> int:
    month = _section("period").get("fiscal_start_month") or 1
    return month if 1 <= month <= 12 else 1


def fiscal_year_start(today: datetime.date) -> datetime.date:
    """The first day of the fiscal year that `today` is in."""
    month = fiscal_start_month()
    year = today.year if today.month >= month else today.year - 1
    return datetime.date(year, month, 1)


# ---- interface
def default_theme() -> str:
    """The theme of `kt.config` (an old key gives the theme that replaced it)."""
    return themes.key(_section("ui").get("theme")) or themes.DEFAULT


def colors_from_theme() -> bool:
    """Whether the graphs and the cards take the colors of the theme (`kt.config`
    says `theme`, the default), not the ones of `kt.config` (`config`)."""
    return _section("ui").get("colors", "theme") == "theme"


def table_rows() -> int:
    """Rows a table tile shows (what the tile holds beyond scrolls or is left out)."""
    rows = _section("ui").get("table_rows") or 20
    return max(1, rows)


# ---- explore
def explore_allowed(is_manager: bool) -> bool:
    """Whether the user may download the rows of a panel (`Explore`) : nobody, the
    KpiTen managers, or everyone (the default)."""
    access = _section("explore").get("access") or "everyone"
    return access == "everyone" or (access == "managers" and is_manager)


def explore_max_rows(default: int) -> int:
    """Rows per table of an export, `default` (the environment) when not set."""
    return _section("explore").get("max_rows") or default


def ods_max_rows() -> int:
    """Rows of a model downloaded as .ods (50 000 when Odoo sets none)."""
    return _section("explore").get("ods_max_rows") or 50_000


# ---- AI (marimo explorer)
def ai_enabled() -> bool:
    return bool(_section("ai").get("enabled", True))


def ai_send_values() -> bool:
    return bool(_section("ai").get("send_values", True))


# ---- new features (off until Odoo turns them on)
FEATURES = (
    "save_tile",
    "alerts",
    "concentration",
    "outliers",
    "export_ods",
    "ai_refine",
    "open_in_odoo",
)


def feature(name: str) -> bool:
    """Whether a new function of the marimo explorer is on : off unless `kt.config`
    (Odoo) says yes, so an older kpiten module, or a database that did not check it,
    keeps things as they were."""
    return bool(_section("features").get(name, False))
