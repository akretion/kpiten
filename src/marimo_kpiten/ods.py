"""A table as an OpenDocument spreadsheet (.ods) : LibreOffice, Excel and Google Sheets
open it. Numbers stay numbers, dates stay dates, and the cells put in relief keep their
color (`recipes.cell_fills` : the same cells as the table on the page).

The file is written by kpiten-core (`kpiten_core.ods.write_ods`, see docs/kpiten-ods.md) :
the header row stays in view and is repeated on each printed page, the columns are as
wide as their content.
"""

import polars as pl

from kpiten_core.ods import write_ods


def to_ods(
    frame: pl.DataFrame,
    fills: dict | None = None,
    sheet: str = "KPI",
    bold_fills: bool = True,
) -> bytes:
    """The .ods file of a table. `fills` is `{(column, row): "#rrggbb"}` (in bold, unless
    `bold_fills` is off : a heat map)."""
    return write_ods([(sheet, frame, fills)], bold_fills=bold_fills)
