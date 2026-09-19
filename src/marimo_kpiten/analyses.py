"""The analyses of the front : one notebook each, in `notebooks/<key>.py`.

A notebook whose name starts with `_` is not served (`_index.py` is the list).
"""

ANALYSES = {
    "explore": {
        "icon": "\U0001f50e",
        "title": "Data explorer",
        "about": "Pick a table you may read and explore it with an AI that writes the polars",
    },
    "purchase": {
        "icon": "\U0001f6d2",
        "title": "Purchase analysis",
        "about": "Spend, vendors and orders, compared with the previous period",
    },
}
