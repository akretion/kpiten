"""The name and the slogan of KpiTen, said the same way by every app.

The logo is a ship's wheel ("barre") whose centre is a bar chart, with a small 10 on its
tallest bar : the wheel of the captain of your KPIs.
"""

NAME = "KpiTen"
SLOGAN = "Le capitaine de vos KPI"


def tooltip() -> str:
    """The text of the tooltip of the logo : the name and the slogan."""
    return f"{NAME} — {SLOGAN}"
