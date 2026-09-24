"""What the Odoo backends share : the fields of a tile and the dict the fronts get."""

import json

# the fields of `kt.dataset.line` a front reads (`table_view` : kpiten 1.x only)
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
        "table_view": rec.get("table_view") or "table",
    }
    if model is not None:
        tile["model"] = model
    return tile
