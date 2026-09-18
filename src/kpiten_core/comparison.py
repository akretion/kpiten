"""How the comparison of a card with the previous period is drawn (both fronts).

The colors and the arrows are the ones of an Odoo scorecard (`baselineColorUp`,
`baselineColorDown`, arrow up / down).
"""

import html

COLORS = {"up": "#00A04A", "down": "#DC6965", "neutral": None}
ARROWS = {"up": "▲", "down": "▼", "neutral": ""}


def label(comparison: dict) -> str:
    """`▲ 12.3%`, or `0.0%` when nothing changed."""
    arrow = ARROWS[comparison["direction"]]
    return f"{arrow} {comparison['text']}".strip()


def tooltip(comparison: dict) -> str:
    """`Previous period 2026-04-20 → 2026-06-18 : 41 000`."""
    period = f" {comparison['period']}" if comparison.get("period") else ""
    return f"Previous period{period} : {comparison['previous']}"


def html_block(comparison: dict) -> str:
    """The line under a card's value, as html (escaped)."""
    color = COLORS[comparison["direction"]]
    style = f' style="color: {color}"' if color else ""
    return (
        f'<div class="kpi-delta"{style} title="{html.escape(tooltip(comparison), quote=True)}">'
        f"{html.escape(label(comparison))} "
        f'<span class="kpi-delta-descr">{html.escape(comparison["description"])}</span></div>'
    )
