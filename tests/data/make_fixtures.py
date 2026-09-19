"""Regenerate the real-data fixtures of the tests (run in an Odoo shell : `make sample-fixtures`).

For each model of the demo dashboards : a sample of the rows, as the KpiTen store holds them
(`parquet_sample`, style "store"), and the tiles of their datasets (`tiles.json`) with the filter
config of their panel. The tests run every tile, and its drill-down, on these samples : no Odoo,
but the real columns.
"""

import json
import pathlib

DATA = pathlib.Path("src/kpiten-core/tests/data")
MODELS = ["sale.order", "sale.order.line", "purchase.order", "purchase.order.line"]
SIZE = 300

sampler, kt = env["parquet.sample"], env["kt"]
# a line belongs to a sampled order : a drill-down from an order finds its lines
PARENT = {
    "sale.order.line": ("sale.order", "order_id"),
    "purchase.order.line": ("purchase.order", "order_id"),
}
ids = {}
for model in MODELS:
    parent = PARENT.get(model)
    frame = sampler.sample_dataframe(
        model,
        SIZE * 20 if parent else SIZE,
        style="store",
        extra_paths=sorted(kt._get_relational_paths_for_model(model)),
        domain=[(parent[1], "in", ids[parent[0]])] if parent else None,
    )
    ids[model] = frame["id"].to_list()
    frame.write_parquet(DATA / f"{model}.parquet")

tiles = []
for line in env["kt.dataset.line"].search(
    [("dataset_id.model_id.model", "in", MODELS), ("panel_id", "!=", False)]
):
    config = json.loads(line.panel_id.filter_config or "{}")
    tiles.append(
        {
            "name": line.name,
            "kind": line.kind,
            "model": line.dataset_id.model_id.model,
            "definition": line.definition,
            "drill": line.drill_definition or None,
            "panel": line.panel_id.name,
            "filter_config": config,
        }
    )
(DATA / "tiles.json").write_text(json.dumps(tiles, indent=1, ensure_ascii=False))
print("FIXTURES", len(MODELS), "samples,", len(tiles), "tiles")
