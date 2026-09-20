"""The name and the slogan of KpiTen, said the same way by every app.

The logo is a ship's wheel ("barre") whose centre is a bar chart, with a small 10 on its
tallest bar : the wheel of the captain of your KPIs.
"""

import functools
import pathlib

NAME = "KpiTen"
SLOGAN = "Le capitaine de vos data"


def tooltip() -> str:
    """The text of the tooltip of the logo : the slogan."""
    return SLOGAN


LOCKUP = pathlib.Path(__file__).parent / "assets" / "kpiten-logo.svg"


@functools.cache
def _lockup() -> str:
    return LOCKUP.read_text()


def lockup_svg(height: int = 44) -> str:
    """The logo with the name and the slogan, as inline svg of the given height : its text
    takes the color of the page (`currentColor`), so it reads on a dark theme and a light one.
    """
    width = round(height * 760 / 220)
    return _lockup().replace(
        'width="760" height="220"', f'width="{width}" height="{height}"'
    )
