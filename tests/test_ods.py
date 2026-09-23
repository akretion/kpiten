import datetime
import shutil
import subprocess
import zipfile
from io import BytesIO

import polars as pl
import pytest

from marimo_kpiten import ods, recipes

FRAME = pl.DataFrame(
    {
        "vendor": ["Ann", "Bob", None],
        "spend": [500.0, 300.0, 50.0],
        "orders": [10, 6, 1],
        "day": [datetime.date(2026, 1, 5), datetime.date(2026, 2, 5), None],
        "late": [True, False, None],
    }
)


def content(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert (
            archive.read("mimetype")
            == b"application/vnd.oasis.opendocument.spreadsheet"
        )
        return archive.read("content.xml").decode()


def test_the_types_of_the_cells_are_kept():
    xml = content(ods.to_ods(FRAME))
    assert 'office:value="500.0"' in xml and 'office:value="10"' in xml  # numbers
    assert 'office:date-value="2026-01-05"' in xml  # a date is a date
    assert 'office:boolean-value="true"' in xml
    assert ">Ann<" in xml and ">vendor<" in xml  # text, and the header


def test_the_cells_in_relief_keep_their_color():
    fills = recipes.cell_fills(FRAME.select("vendor", "spend"), "alert_above", 200)
    assert len(fills) == 2  # 500 and 300
    xml = content(ods.to_ods(FRAME, fills))
    assert recipes.RED in xml
    bold = 'fo:font-weight="bold"'
    # the header is bold, and so are the cells in relief unless it is a heat map
    assert xml.count(bold) == 2  # the header style, the red style
    assert content(ods.to_ods(FRAME, fills, bold_fills=False)).count(bold) == 1


def test_a_frame_without_rows_is_still_a_file():
    xml = content(
        ods.to_ods(
            pl.DataFrame({"a": [], "b": []}, schema={"a": pl.String, "b": pl.Float64})
        )
    )
    assert ">a<" in xml and ">b<" in xml


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice is not installed")
def test_libreoffice_reads_the_file_back(tmp_path):
    path = tmp_path / "kpi.ods"
    # a date put in relief stays a date
    frame = FRAME.select("vendor", "spend", "orders", "day")
    path.write_bytes(
        ods.to_ods(frame, {("day", 0): "#ffcccc", ("spend", 1): "#ffcccc"})
    )
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "csv",
            "--outdir",
            str(tmp_path),
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    lines = (tmp_path / "kpi.csv").read_text().strip().splitlines()
    assert lines[0] == "vendor,spend,orders,day"
    assert lines[1] == "Ann,500,10,2026-01-05"
    assert lines[2].startswith("Bob,300")
