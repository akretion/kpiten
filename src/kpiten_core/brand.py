"""The name and the slogans of KpiTen, said the same way by every app.

"KPI-Ten" is pronounced like "capitaine" (captain) in French : hence the wheel of the logo
(the "barre" of a ship, and the "barres" of a chart) and its little "10".
"""

NAME = "KpiTen"
SLOGAN = "Le capitaine de vos KPI"
# said under the logo, on hover : the slogan, and the pun that explains the logo
EXPLANATION = (
    "« KPI-Ten » se prononce comme « capitaine » : prenez la barre de vos KPI."
)


def tooltip() -> str:
    """The text of the tooltip of the logo (two lines)."""
    return f"{NAME} — {SLOGAN}\n{EXPLANATION}"
