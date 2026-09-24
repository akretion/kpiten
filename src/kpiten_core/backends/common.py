"""What the Odoo backends share : the fields of a tile and the dict the fronts get."""

import json

# the fields of `kt.dataset.line` a front reads
TILE_FIELDS = [
    "id",
    "dataset_id",
    "definition",
    "name",
    "kind",
    "col_span",
    "tile_height",
    "drill_definition",
]
# ... and the ones a kpiten module older than them does not have (read when it has)
OPTIONAL_TILE_FIELDS = ["table_view", "display"]


def tile_fields(fields_get) -> list[str]:
    """`TILE_FIELDS` and the optional ones the module has (`fields_get(names)` : the
    `fields_get` of `kt.dataset.line`)."""
    known = fields_get(OPTIONAL_TILE_FIELDS)
    return TILE_FIELDS + [name for name in OPTIONAL_TILE_FIELDS if name in known]


def parse_filter_config(raw):
    if not raw:
        return {}
    return json.loads(raw)


def tile_dict(rec: dict, model: str | None = None) -> dict:
    """A `kt.dataset.line` as read by Odoo -> the tile of a front."""
    dataset = rec["dataset_id"]
    tile = {
        "id": rec["id"],
        "dataset_id": dataset[0] if isinstance(dataset, (list, tuple)) else dataset,
        "content": rec["definition"],
        "name": rec["name"],
        "kind": rec["kind"],
        "col_span": rec["col_span"],
        "tile_height": rec["tile_height"],
        "drill": rec["drill_definition"] or None,
        "display": rec.get("display") or None,  # a data tile : [labels], [table]
        "table_view": rec.get("table_view") or "table",
    }
    if model is not None:
        tile["model"] = model
    return tile
