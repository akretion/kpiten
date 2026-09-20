"""What differs between the Odoo series this module runs on (see
`scripts/downgrade.py` for the views, which are written for the latest series).

Only the Python side lives here : one place to look when a new series comes.
"""

from odoo import release

try:
    import tomllib  # Python 3.11+
except ImportError:  # Odoo 16 runs on older Pythons
    import tomli as tomllib

SERIES = release.version_info[0]

# name of the list view / view mode : `tree` before Odoo 18
LIST = "list" if SERIES >= 18 else "tree"

__all__ = ["LIST", "SERIES", "tomllib"]
