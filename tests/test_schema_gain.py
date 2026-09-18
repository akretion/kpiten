"""Schema-change handling : new Odoo columns on an existing parquet.

The delta merge adds a new column to the stored parquet with NULL on the
already-stored rows (no full re-extraction).
"""

import os
import tempfile

import polars as pl
import pytest

from kpiten_core import env
from kpiten_core.store import DFStorage


def _setup():
    tmp = tempfile.mkdtemp()
    env.data_path = tmp
    env.current_db = "testdb"
    # one existing row, no extra column yet
    DFStorage.store_raw(
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


def test_scan_df_is_lazy_and_applies_acl_and_lang():
    tmp = _setup()
    df = pl.DataFrame(
        {
            "id": [1, 2],
            "name": [
                {"fr_FR": "Chaise", "en_US": "Chair"},
                {"fr_FR": "Table", "en_US": "Desk"},
            ],
            "secret": ["a", "b"],
        }
    )
    DFStorage.store_raw("product", [], {}, df)
    lazy = DFStorage.scan_df("product", allowed_fields=["id", "name"], lang="fr_FR")
    assert isinstance(lazy, pl.LazyFrame)
    assert lazy.collect().to_dict(as_series=False) == {
        "id": [1, 2],
        "name": ["Chaise", "Table"],
    }
    # a language absent from the data falls back on en_US instead of failing
    lazy = DFStorage.scan_df("product", allowed_fields=["id", "name"], lang="de_DE")
    assert lazy.collect()["name"].to_list() == ["Chair", "Desk"]
    # parquet written atomically : no tmp file left behind
    assert not [f for f in os.listdir(f"{tmp}/testdb") if f.endswith(".tmp")]
    with pytest.raises(Exception, match="No such table"):
        DFStorage.scan_df("nothing")
