"""The names shown for the columns of a tile (axes of a graph, headers of a pivot).

In this order : the `[labels]` of the tile (`amount_untaxed = "HT"`), else the label of
the field in Odoo in the language of the user (`Montant HT`), else the technical name
tidied (`amount_untaxed` -> `Amount untaxed`) : a computed column, a dotted path.
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# model -> {field: label}, in the language of the user (see `field_labels_of`)
FieldLabels = Callable[[str], dict[str, str]]

# (db, model, lang) -> {field: label} : the labels of the fields change with a module
# update only, a restart of the front clears them
_CACHE: dict[tuple, dict[str, str]] = {}


def tidy(name: str) -> str:
    """`amount_untaxed` -> `Amount untaxed` (what the tiles showed before)."""
    return name.replace("_", " ").capitalize()


def column_label(
    name: str, tile_labels: Optional[dict] = None, fields: Optional[dict] = None
) -> str:
    if tile_labels and name in tile_labels:
        return tile_labels[name]
    if fields and name in fields:
        return fields[name]
    return tidy(name)


def field_labels_of(backend, lang: Optional[str]) -> FieldLabels:
    """The `field_labels` a front gives to `tiles.exec_tile` : the labels of the fields
    of a model in `lang`, read once per model. An error leaves the tidied names."""

    def labels(model: str) -> dict[str, str]:
        key = (backend.db, model, lang)
        if key not in _CACHE:
            try:
                _CACHE[key] = backend.get_field_labels(model, lang)
            except Exception:
                logger.exception("the labels of the fields of %s are unknown", model)
                return {}
        return _CACHE[key]

    return labels
