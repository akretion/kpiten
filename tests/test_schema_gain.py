"""Schema-change handling : new Odoo columns on an existing parquet.

The delta merge adds a new column to the stored parquet with NULL on the
already-stored rows (no full re-extraction).
"""

import tempfile

import polars as pl

from kpiten_core import env
from kpiten_core.store import DFStorage


def _setup():
    tmp = tempfile.mkdtemp()
    env.data_path = tmp
    env.current_db = "testdb"
    # one existing row, no extra column yet
    DFStorage.init_table(
        "sale.order",
        [{"id": 1, "state": "done"}],
        {},
        pl.DataFrame({"id": [1], "state": ["done"]}),
    )
    return tmp


def test_append_records_adds_new_column():
    _setup()
    DFStorage.append_records("sale.order", [{"id": 2, "state": "draft", "priority": 5}])
    out = DFStorage.retrieve_df("sale.order")["df"]
    assert "priority" in out.columns
    # old row keeps its NULL for the new column, new row has the value
    by_id = out.select(["id", "priority"]).sort("id").to_dicts()
    assert by_id[0] == {"id": 1, "priority": None}
    assert by_id[1] == {"id": 2, "priority": 5}


def test_append_records_no_new_column_leaves_schema():
    _setup()
    DFStorage.append_records("sale.order", [{"id": 2, "state": "draft"}])
    out = DFStorage.retrieve_df("sale.order")["df"]
    assert out.columns == ["id", "state"]
