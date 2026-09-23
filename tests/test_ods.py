"""The rows of a panel as an .ods : ready to read and to print."""

import datetime
import io
import zipfile

import polars as pl
import pytest

from kpiten_core import config, ods


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
    # without it LibreOffice ignores the view settings, the freeze with them
    assert 'xmlns:ooo="http://openoffice.org/2004/office"' in settings
    content = archive.read("content.xml").decode()
    assert "<table:table-header-rows>" in content
    # the partner as wide as its longest name, the amount as its header
    assert ods._widths(df) == [26, 7, 10]
    assert 'style:name="co26"' in content and 'style:name="co7"' in content


def test_one_model_one_sheet_filtered_no_ids_cut_as_kt_config_says():
    store = {
        "sale.order": pl.LazyFrame(
            {"id": range(60_000), "partner_id": ["Azure"] * 60_000}
        ).with_columns(partner_id_=pl.lit(7), incoterm_=pl.lit(3))
    }
    config.set_config({"explore": {"ods_max_rows": 50_000}})
    predicates = [pl.col("id") >= 5_000, pl.col("missing") == 1]  # not on the table
    name, data, note = ods.model_ods(
        store, "sale.order", predicates, user_id=2, db="claude"
    )
    config.set_config({})
    assert name == "kpiten-claude-sale.order.ods"
    assert note == "first 50000 of 55000 rows"
    content = zipfile.ZipFile(io.BytesIO(data)).read("content.xml").decode()
    assert content.count("<table:table ") == 1
    assert (
        "partner_id_" not in content
        and "incoterm_" not in content
        and "Azure" in content
    )
    with pytest.raises(PermissionError):
        ods.model_ods(store, "purchase.order", [], user_id=2, db="claude")
