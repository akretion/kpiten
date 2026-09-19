"""A table as an OpenDocument spreadsheet (.ods) : LibreOffice, Excel and Google Sheets
open it. Numbers stay numbers, dates stay dates, and the cells put in relief keep their
color (`recipes.cell_fills` : the same cells as the table on the page).
"""

import datetime
import decimal
import io

import polars as pl
from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableCellProperties, TextProperties
from odf.table import Table, TableCell, TableColumn, TableRow
from odf.text import P

HEADER_FILL = "#f3f4f6"


def _cell(value, style_name: str | None):
    """One cell of the right type : the spreadsheet can add up what is a number."""
    args = {"stylename": style_name} if style_name else {}
    if value is None:
        return TableCell(**args)
    if isinstance(value, bool):
        cell = TableCell(valuetype="boolean", booleanvalue=str(value).lower(), **args)
    elif isinstance(value, (int, float, decimal.Decimal)):
        cell = TableCell(valuetype="float", value=float(value), **args)
    elif isinstance(value, datetime.datetime):
        cell = TableCell(valuetype="date", datevalue=value.isoformat(), **args)
    elif isinstance(value, datetime.date):
        cell = TableCell(valuetype="date", datevalue=value.isoformat(), **args)
    else:
        cell = TableCell(valuetype="string", **args)
    cell.addElement(P(text=str(value)))
    return cell


def to_ods(
    frame: pl.DataFrame,
    fills: dict | None = None,
    sheet: str = "KPI",
    bold_fills: bool = True,
) -> bytes:
    """The .ods file of a table. `fills` is `{(column, row): "#rrggbb"}` (in bold, unless
    `bold_fills` is off : a heat map)."""
    fills = fills or {}
    document = OpenDocumentSpreadsheet()
    styles: dict = {}

    def style(background: str, bold: bool = False) -> str:
        key = (background, bold)
        if key not in styles:
            name = f"cell{len(styles)}"
            cell_style = Style(name=name, family="table-cell")
            cell_style.addElement(TableCellProperties(backgroundcolor=background))
            if bold:
                cell_style.addElement(TextProperties(fontweight="bold"))
            document.automaticstyles.addElement(cell_style)
            styles[key] = name
        return styles[key]

    table = Table(name=sheet[:31])
    table.addElement(TableColumn(numbercolumnsrepeated=max(len(frame.columns), 1)))
    header = TableRow()
    for name in frame.columns:
        header.addElement(_cell(name, style(HEADER_FILL, bold=True)))
    table.addElement(header)
    for index, row in enumerate(frame.iter_rows()):
        line = TableRow()
        for name, value in zip(frame.columns, row):
            color = fills.get((name, index))
            line.addElement(_cell(value, style(color, bold_fills) if color else None))
        table.addElement(line)
    document.spreadsheet.addElement(table)
    out = io.BytesIO()
    document.write(out)
    return out.getvalue()
