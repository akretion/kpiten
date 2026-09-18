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


def _blocks(tmp, table):
    d = f"{tmp}/testdb/{table}"
    return {f: os.stat(f"{d}/{f}").st_mtime_ns for f in sorted(os.listdir(d))}


def test_table_is_stored_in_id_blocks_and_a_delta_rewrites_only_its_blocks(monkeypatch):
    tmp = _setup()
    monkeypatch.setattr(env, "partition_size", 10)
    df = pl.DataFrame({"id": [1, 5, 12, 25, 26], "v": list("abcde")})
    DFStorage.store_raw("t", [], {}, df)
    before = _blocks(tmp, "t")
    assert list(before) == ["000000.parquet", "000001.parquet", "000002.parquet"]

    # upsert : id 26 (block 2) changes, id 27 (block 2) is new
    DFStorage.merge_df("t", pl.DataFrame({"id": [27, 26], "v": ["f", "E"]}))
    after = _blocks(tmp, "t")
    assert after["000000.parquet"] == before["000000.parquet"]
    assert after["000001.parquet"] == before["000001.parquet"]
    assert after["000002.parquet"] != before["000002.parquet"]
    out = DFStorage.retrieve_df("t")["df"]
    assert out["id"].to_list() == [1, 5, 12, 25, 26, 27]  # blocks in id order
    assert out["v"].to_list() == ["a", "b", "c", "d", "E", "f"]

    # a deletion only touches the block of the id ; blocks are never removed
    before = _blocks(tmp, "t")
    assert DFStorage.delete_records("t", [12, 999]) == 1
    after = _blocks(tmp, "t")
    assert after["000001.parquet"] != before["000001.parquet"]
    assert after["000000.parquet"] == before["000000.parquet"]
    assert set(after) == set(before)
    assert DFStorage.retrieve_df("t")["df"]["id"].to_list() == [1, 5, 25, 26, 27]


def test_blocks_with_drifting_schemas_are_read_as_one_table(monkeypatch):
    """Each block is normalized on its own rows : a decimal scale or an all null
    column can differ from a block to another."""
    _setup()
    monkeypatch.setattr(env, "partition_size", 10)
    DFStorage.write_block(
        "t",
        0,
        pl.DataFrame(
            {
                "id": [1],
                "amount": pl.Series([1.5], dtype=pl.Decimal(10, 1)),
                "note": pl.Series([None], dtype=pl.Null),
            }
        ),
    )
    DFStorage.write_block(
        "t",
        1,
        pl.DataFrame(
            {
                "id": [11],
                "amount": pl.Series([2.25], dtype=pl.Decimal(10, 2)),
                "note": ["x"],
                "extra": [7],
            }
        ),
    )
    DFStorage.commit_full(
        "t", {}, {0, 1}, ["id", "amount", "note", "extra"], "2026-01-01 00:00:00"
    )
    out = DFStorage.retrieve_df("t")["df"]
    assert out.columns == ["id", "amount", "note", "extra"]
    assert out["amount"].to_list() == [pytest.approx(1.5), pytest.approx(2.25)]
    assert out["note"].to_list() == [None, "x"]
    assert out["extra"].to_list() == [None, 7]


def test_delta_keeps_the_wider_decimal_scale():
    _setup()
    dec = lambda v, scale: pl.Series([v], dtype=pl.Decimal(10, scale))
    DFStorage.store_raw("t", [], {}, pl.DataFrame({"id": [1], "amount": dec(1.5, 1)}))
    DFStorage.merge_df("t", pl.DataFrame({"id": [2], "amount": dec(2.125, 3)}))
    out = DFStorage.retrieve_df("t")["df"]
    assert str(out["amount"][1]) == "2.125"  # not rounded to the stored scale


def test_legacy_single_file_is_read_until_a_full_sync_migrates_it(monkeypatch):
    tmp = _setup()
    monkeypatch.setattr(env, "partition_size", 10)
    legacy = pl.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    legacy.write_parquet(f"{tmp}/testdb/old.parquet")
    assert "old" in DFStorage.list_table_names()
    assert DFStorage.retrieve_df("old")["df"]["v"].to_list() == ["a", "b"]
    with pytest.raises(Exception, match="full sync"):
        DFStorage.merge_df("old", legacy)

    # blocks being written are not readable before the extraction is sealed
    DFStorage.write_block("old", 0, pl.DataFrame({"id": [1], "v": ["A"]}))
    assert DFStorage.retrieve_df("old")["df"]["v"].to_list() == ["a", "b"]
    DFStorage.commit_full("old", {}, {0}, ["id", "v"], "2026-01-01 00:00:00")
    assert DFStorage.retrieve_df("old")["df"]["v"].to_list() == ["A"]
    assert not os.path.exists(f"{tmp}/testdb/old.parquet")
    assert DFStorage.last_sync("old") == "2026-01-01 00:00:00"


def test_full_extraction_seal_empties_stale_blocks_instead_of_removing_them(
    monkeypatch,
):
    tmp = _setup()
    monkeypatch.setattr(env, "partition_size", 10)
    DFStorage.store_raw("t", [], {}, pl.DataFrame({"id": [1, 11], "v": ["a", "b"]}))
    DFStorage.store_raw("t", [], {}, pl.DataFrame({"id": [1], "v": ["a"]}))
    assert sorted(os.listdir(f"{tmp}/testdb/t")) == ["000000.parquet", "000001.parquet"]
    assert DFStorage.retrieve_df("t")["df"]["id"].to_list() == [1]


def test_column_order_is_the_one_of_the_whole_table(monkeypatch):
    """Constant columns last, `_` columns before them : even when the table is
    only ever seen block by block."""
    from kpiten_core.store import ColumnOrder

    order = ColumnOrder()
    order.update(pl.DataFrame({"a": [1], "k": ["x"], "p_id_": [3], "b": [1]}))
    order.update(pl.DataFrame({"a": [2], "k": ["x"], "p_id_": [4], "b": [1]}))
    assert order.order() == ["a", "p_id_", "k", "b"]
