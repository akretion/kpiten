"""What the Odoo backends share : the fields of a tile and the dict the fronts get."""

import json

# the model of the tiles ; `kt.dataset.line` before the kpiten module 1.5.0 (a base
# not updated yet : the backends ask which one it has)
KPI_MODEL = "kt.kpi"
LEGACY_KPI_MODEL = "kt.dataset.line"

# the fields of `kt.kpi` a front reads
TILE_FIELDS = [
    "id",
    "dataset_id",
    "definition",
    "name",
    "kind",
    "drill_definition",
]
# ... and the ones a kpiten module older than them does not have (read when it has)
OPTIONAL_TILE_FIELDS = ["table_view", "display"]

# a KPI on a panel (`kt.panel.tile`) : its place and its size there ; a KPI may be on
# several panels
PLACEMENT_MODEL = "kt.panel.tile"
PLACEMENT_FIELDS = ["kpi_id", "col_span", "tile_height"]


def placements_domain(panel_id: int) -> list:
    """The KPIs of a panel, the archived ones left out, in their order."""
    return [("panel_id", "=", panel_id), ("kpi_id.active", "=", True)]


def tile_fields(fields_get) -> list[str]:
    """`TILE_FIELDS` and the optional ones the module has (`fields_get(names)` : the
    `fields_get` of `kt.kpi`)."""
    known = fields_get(OPTIONAL_TILE_FIELDS)
    return TILE_FIELDS + [name for name in OPTIONAL_TILE_FIELDS if name in known]


def parse_filter_config(raw):
    if not raw:
        return {}
    return json.loads(raw)


def tile_dict(rec: dict, model: str | None = None) -> dict:
    """A `kt.kpi` as read by Odoo -> the tile of a front."""
    dataset = rec["dataset_id"]
    tile = {
        "id": rec["id"],
        "dataset_id": dataset[0] if isinstance(dataset, (list, tuple)) else dataset,
        "content": rec["definition"],
        "name": rec["name"],
        "kind": rec["kind"],
        # its size on the panel : `panel_tiles` sets it
        "col_span": rec.get("col_span") or 1,
        "tile_height": rec.get("tile_height"),
        "drill": rec["drill_definition"] or None,
        "display": rec.get("display") or None,  # a data tile : [labels], [table]
        "table_view": rec.get("table_view") or "table",
    }
    if model is not None:
        tile["model"] = model
    return tile


def model_names(call, dataset_ids) -> dict[int, str]:
    """dataset id -> the technical name of its model (`call` : the backend's)."""
    datasets = call(
        "kt.dataset", "read", ids=list(set(dataset_ids)), fields=["model_id"]
    )
    model_ids = {ds["model_id"][0] for ds in datasets}
    names = {
        m["id"]: m["model"]
        for m in call("ir.model", "read", ids=list(model_ids), fields=["model"])
    }
    return {ds["id"]: names[ds["model_id"][0]] for ds in datasets}


def read_panel_tiles(call, kpi_model: str, fields: list[str], panel_id: int):
    """The tiles of a panel, in its order : each KPI with its size on the panel
    (`kt.panel.tile`) and the technical name of its model. `call` : the backend's
    `call(model, method, ids=..., **kwargs)`."""
    placements = call(
        PLACEMENT_MODEL,
        "search_read",
        domain=placements_domain(panel_id),
        fields=PLACEMENT_FIELDS,
    )
    if not placements:
        return []
    kpis = call(
        kpi_model, "read", ids=[p["kpi_id"][0] for p in placements], fields=fields
    )
    by_id = {kpi["id"]: kpi for kpi in kpis}
    models = model_names(call, [kpi["dataset_id"][0] for kpi in kpis])
    tiles = []
    for place in placements:
        kpi = by_id.get(place["kpi_id"][0])
        if kpi is None:
            continue
        tile = tile_dict(kpi, models[kpi["dataset_id"][0]])
        tile["col_span"] = place["col_span"] or 1
        tile["tile_height"] = place["tile_height"]
        tiles.append(tile)
    return tiles
