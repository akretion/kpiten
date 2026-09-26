"""The analyses of the front : one notebook each, in `notebooks/<key>.py`.

A notebook whose name starts with `_` is not served (`_index.py` is the list).
"""

ANALYSES = {
    "explore": {
        "icon": "\U0001f50e",
        "title": "Data explorer",
        "about": "Pick a table you may read and explore it with an AI that writes the polars",
    },
    "derived": {
        "icon": "\U0001fa9c",
        "title": "Query and steps",
        "about": "Ask or write a query on your tables : its result, or its steps explained",
    },
}
