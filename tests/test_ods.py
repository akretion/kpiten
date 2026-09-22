"""The rows of a panel as an .ods : ready to read and to print."""

import datetime
import io
import zipfile

import polars as pl

from kpiten_core import ods


def test_the_ods_is_landscape_its_header_frozen_its_columns_fitted():
    df = pl.DataFrame(
        {
            "Partner": ["Marie STOURNE", "A partner with a long name"],
            "Amount": [12.5, 1234.0],
            "Date": [datetime.date(2026, 1, 2), None],
        }
    )
    archive = zipfile.ZipFile(io.BytesIO(ods.write_ods([("Sales & co", df)])))
    assert 'style:print-orientation="landscape"' in archive.read("styles.xml").decode()
    settings = archive.read("settings.xml").decode()
    assert 'config:name="Sales &amp; co"' in settings
    assert 'VerticalSplitPosition" config:type="int">1<' in settings
    content = archive.read("content.xml").decode()
    assert "<table:table-header-rows>" in content
    # the partner as wide as its longest name, the amount as its header
    assert ods._widths(df) == [26, 7, 10]
    assert 'style:name="co26"' in content and 'style:name="co7"' in content


def test_no_more_than_50_000_rows_per_sheet():
    lines = [{"kind": "data", "model": "sale.order", "name": "Orders"}]
    store = {"sale.order": pl.DataFrame({"id": range(60_000)})}
    _name, data = ods.build_ods(
        store, lines, [], user_id=2, db="claude", panel="Sales", max_rows=100_000
    )
    content = zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()
    assert "first 50000 of 60000 rows" in content
