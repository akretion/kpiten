"""How the comparison of a card with the previous period is drawn (both fronts).

The colors and the arrows are the ones of an Odoo scorecard (`baselineColorUp`,
`baselineColorDown`, arrow up / down).
"""

import html

from kpiten_core import config

# the color follows the tone (good / bad), the arrow follows the direction : a fall
# of the late deliveries is drawn ▼ in green (`good = "down"` on the card)
COLORS = {"good": "#00A04A", "bad": "#DC6965", "neutral": None}
ARROWS = {"up": "▲", "down": "▼", "neutral": ""}
_TONE_OF_DIRECTION = {"up": "good", "down": "bad", "neutral": "neutral"}


def tone(comparison: dict) -> str:
    """good / bad / neutral (a result without a tone : up is good)."""
    return comparison.get("tone") or _TONE_OF_DIRECTION[comparison["direction"]]


def color(comparison: dict, palette: dict | None = None) -> str | None:
    """The color of a tone : those of `kt.config` (the card colors), else the ones of
    the theme (`palette`), else Odoo's."""
    name = tone(comparison)
    if name not in ("good", "bad"):
        return None
    return config.card_color(name, (palette or {}).get(name) or COLORS[name])


def label(comparison: dict) -> str:
    """`▲ 12.3%`, or `0.0%` when nothing changed."""
    arrow = ARROWS[comparison["direction"]]
    return f"{arrow} {comparison['text']}".strip()


def tooltip(comparison: dict) -> str:
    """`Previous period 2026-04-20 → 2026-06-18 : 41 000`."""
    period = f" {comparison['period']}" if comparison.get("period") else ""
    return f"Previous period{period} : {comparison['previous']}"


def html_block(comparison: dict, palette: dict | None = None) -> str:
    """The line under a card's value, as html (escaped)."""
    text_color = color(comparison, palette)
    style = f' style="color: {text_color}"' if text_color else ""
    return (
        f'<div class="kpi-delta"{style} title="{html.escape(tooltip(comparison), quote=True)}">'
        f"{html.escape(label(comparison))} "
        f'<span class="kpi-delta-descr">{html.escape(comparison["description"])}</span></div>'
    )
