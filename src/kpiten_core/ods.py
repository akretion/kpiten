"""The rows of an Odoo model as an OpenDocument spreadsheet (.ods) : one file per model,
the one the user chooses, one sheet per file.

The rows are the raw rows of the user's store (his columns and his rows only), narrowed
by the filters of the panel.

The content is generated column by column with polars expressions (no cell by cell
python loop, no odfpy) : a sheet of 50 000 rows is written in a few seconds.

The file is ready to read and to print : the header row stays in view (frozen) and is
repeated on each printed page, the pages are in landscape, and each column is as wide as
its content.
"""

import io
import json
import logging
import re
import zipfile

import polars as pl

from kpiten_core import config
from kpiten_core.tiles import filter_df

logger = logging.getLogger(__name__)

MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"
MANIFEST = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="{MIMETYPE}"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="settings.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""
NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
    'office:version="1.2"'
)
# printed in landscape (A4), the sheets fitted to the width of the page
STYLES = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {NS}>
<office:automatic-styles>
 <style:page-layout style:name="landscape">
  <style:page-layout-properties fo:page-width="29.7cm" fo:page-height="21cm"
   style:print-orientation="landscape" fo:margin="1cm"
   style:scale-to-X="1" style:scale-to-Y="0"/>
 </style:page-layout>
</office:automatic-styles>
<office:master-styles>
 <style:master-page style:name="Default" style:page-layout-name="landscape"/>
</office:master-styles>
</office:document-styles>
"""
# the header row frozen : set in the view of each sheet
SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0" office:version="1.2">
<office:settings><config:config-item-set config:name="ooo:view-settings">
<config:config-item-map-indexed config:name="Views"><config:config-item-map-entry>
<config:config-item config:name="ViewId" config:type="string">view1</config:config-item>
<config:config-item-map-named config:name="Tables">{tables}</config:config-item-map-named>
</config:config-item-map-entry></config:config-item-map-indexed>
</config:config-item-set></office:settings></office:document-settings>
"""
FROZEN_HEADER = """<config:config-item-map-entry config:name="{name}">
<config:config-item config:name="CursorPositionX" config:type="int">0</config:config-item>
<config:config-item config:name="CursorPositionY" config:type="int">1</config:config-item>
<config:config-item config:name="HorizontalSplitMode" config:type="short">0</config:config-item>
<config:config-item config:name="HorizontalSplitPosition" config:type="int">0</config:config-item>
<config:config-item config:name="VerticalSplitMode" config:type="short">2</config:config-item>
<config:config-item config:name="VerticalSplitPosition" config:type="int">1</config:config-item>
<config:config-item config:name="ActiveSplitRange" config:type="short">2</config:config-item>
<config:config-item config:name="PositionLeft" config:type="int">0</config:config-item>
<config:config-item config:name="PositionRight" config:type="int">0</config:config-item>
<config:config-item config:name="PositionTop" config:type="int">0</config:config-item>
<config:config-item config:name="PositionBottom" config:type="int">1</config:config-item>
</config:config-item-map-entry>"""
# a column as wide as its content, between these widths (in characters)
MIN_CHARS, MAX_CHARS = 4, 60
CM_PER_CHAR = 0.21
# the sheets on the landscape pages, the header row in bold, dates and datetimes shown
# as such (not as numbers) ; the widths of the columns are added by `write_ods`
AUTOMATIC_STYLES = """<office:automatic-styles>
 <style:style style:name="sheet" style:family="table" style:master-page-name="Default"/>
 <style:style style:name="head" style:family="table-cell">
  <style:text-properties fo:font-weight="bold"/>
 </style:style>
 <number:date-style style:name="nd">
  <number:year number:style="long"/><number:text>-</number:text>
  <number:month number:style="long"/><number:text>-</number:text>
  <number:day number:style="long"/>
 </number:date-style>
 <number:date-style style:name="ndt">
  <number:year number:style="long"/><number:text>-</number:text>
  <number:month number:style="long"/><number:text>-</number:text>
  <number:day number:style="long"/><number:text> </number:text>
  <number:hours number:style="long"/><number:text>:</number:text>
  <number:minutes number:style="long"/>
 </number:date-style>
 <style:style style:name="date" style:family="table-cell" style:data-style-name="nd"/>
 <style:style style:name="datetime" style:family="table-cell" style:data-style-name="ndt"/>
{columns}</office:automatic-styles>
"""
EMPTY = "<table:table-cell/>"
# characters XML 1.0 does not allow, even escaped
CONTROL = r"[\x00-\x08\x0b\x0c\x0e-\x1f]"
FORBIDDEN_IN_SHEET_NAME = re.compile(r"[\[\]*?:/\\']")


def _escape(expr: pl.Expr) -> pl.Expr:
    return (
        expr.str.replace_all(CONTROL, "")
        .str.replace_all("&", "&amp;", literal=True)
        .str.replace_all("<", "&lt;", literal=True)
        .str.replace_all(">", "&gt;", literal=True)
        .str.replace_all('"', "&quot;", literal=True)
    )


def _text(value: str) -> str:
    escaped = (
        re.sub(CONTROL, "", value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<table:table-cell office:value-type="string"><text:p>{escaped}</text:p></table:table-cell>'


def _cell(name: str, dtype: pl.DataType) -> pl.Expr:
    """The xml of the cells of one column, as a string expression."""
    col = pl.col(name)
    if dtype == pl.Boolean:
        value = col.cast(pl.String)
        xml = pl.format(
            '<table:table-cell office:value-type="boolean" office:boolean-value="{}">'
            "<text:p>{}</text:p></table:table-cell>",
            value,
            value,
        )
    elif dtype.is_numeric():
        value = col.cast(pl.Float64) if dtype.is_decimal() else col
        value = value.cast(pl.String)
        xml = pl.format(
            '<table:table-cell office:value-type="float" office:value="{}">'
            "<text:p>{}</text:p></table:table-cell>",
            value,
            value,
        )
    elif dtype == pl.Date:
        value = col.dt.strftime("%Y-%m-%d")
        xml = pl.format(
            '<table:table-cell table:style-name="date" office:value-type="date" '
            'office:date-value="{}"><text:p>{}</text:p></table:table-cell>',
            value,
            value,
        )
    elif dtype == pl.Datetime:
        xml = pl.format(
            '<table:table-cell table:style-name="datetime" office:value-type="date" '
            'office:date-value="{}"><text:p>{}</text:p></table:table-cell>',
            col.dt.strftime("%Y-%m-%dT%H:%M:%S"),
            col.dt.strftime("%Y-%m-%d %H:%M"),
        )
    else:
        # strings, and anything else (a list, a struct...) in its text form
        if dtype == pl.String:
            value = col
        elif isinstance(dtype, (pl.List, pl.Array, pl.Struct, pl.Object)):
            value = col.map_elements(str, return_dtype=pl.String)
        else:
            value = col.cast(pl.String)
        value = _escape(value)
        xml = pl.format(
            '<table:table-cell office:value-type="string"><text:p>{}</text:p>'
            "</table:table-cell>",
            value,
        )
    return pl.when(col.is_null()).then(pl.lit(EMPTY)).otherwise(xml)


def _widths(df: pl.DataFrame) -> list[int]:
    """The width of each column, in characters : its longest value or its header."""
    lengths = []
    for name, dtype in df.schema.items():
        if dtype == pl.Date:
            length = pl.lit(10)
        elif dtype == pl.Datetime:
            length = pl.lit(16)
        elif dtype == pl.Boolean:
            length = pl.lit(5)
        elif isinstance(dtype, (pl.List, pl.Array, pl.Struct, pl.Object)):
            length = pl.lit(MAX_CHARS)
        else:
            col = pl.col(name)
            col = col.cast(pl.Float64) if dtype.is_decimal() else col
            length = col.cast(pl.String).str.len_chars().max()
        lengths.append(length.alias(name))
    longest = df.select(lengths).row(0) if df.height else [0] * df.width
    return [
        max(MIN_CHARS, min(MAX_CHARS, max(n or 0, len(name) + 1)))
        for name, n in zip(df.columns, longest)
    ]


def _column_style(chars: int) -> str:
    return f"co{chars}"


def _sheet(name: str, df: pl.DataFrame) -> str:
    columns = "".join(
        f'<table:table-column table:style-name="{_column_style(w)}"/>'
        for w in _widths(df)
    )
    head = "".join(
        _text(c).replace(
            "<table:table-cell ", '<table:table-cell table:style-name="head" ', 1
        )
        for c in df.columns
    )
    rows = ""
    if df.height and df.width:
        cells = [_cell(c, t).alias(c) for c, t in df.schema.items()]
        lines = df.select(
            pl.concat_str(
                [pl.lit("<table:table-row>"), *cells, pl.lit("</table:table-row>")]
            ).alias("xml")
        )
        rows = "\n".join(lines["xml"].to_list())
    # the header row is repeated on each printed page
    return (
        f'<table:table table:name="{name}" table:style-name="sheet">{columns}'
        "<table:table-header-rows>"
        f"<table:table-row>{head}</table:table-row>"
        f"</table:table-header-rows>\n{rows}</table:table>"
    )


def _sheet_name(title: str, taken: set[str]) -> str:
    """A name LibreOffice accepts, unique in the file (`Sales (2)`...)."""
    base = FORBIDDEN_IN_SHEET_NAME.sub(" ", title).strip()[:28] or "Sheet"
    name, n = base, 2
    while name.lower() in taken:
        name, n = f"{base} ({n})", n + 1
    taken.add(name.lower())
    return name.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def write_ods(sheets: list[tuple[str, pl.DataFrame]]) -> bytes:
    """The bytes of an .ods holding each `(title, dataframe)` as a sheet."""
    taken: set[str] = set()
    names = [_sheet_name(t, taken) for t, _df in sheets]
    body = "\n".join(_sheet(name, df) for name, (_t, df) in zip(names, sheets))
    widths = sorted({w for _t, df in sheets for w in _widths(df)})
    columns = "".join(
        f' <style:style style:name="{_column_style(w)}" style:family="table-column">'
        f'<style:table-column-properties style:column-width="{w * CM_PER_CHAR + 0.3:.2f}cm"/>'
        "</style:style>\n"
        for w in widths
    )
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {NS}>'
        f"{AUTOMATIC_STYLES.format(columns=columns)}"
        f"<office:body><office:spreadsheet>{body}"
        "</office:spreadsheet></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # the mimetype first and not compressed : how a reader recognizes the file
        zf.writestr("mimetype", MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", MANIFEST)
        zf.writestr("styles.xml", STYLES)
        zf.writestr("content.xml", content)
        tables = "".join(FROZEN_HEADER.format(name=name) for name in names)
        zf.writestr("settings.xml", SETTINGS.format(tables=tables))
    return buffer.getvalue()


def exportable_models(store: dict) -> list[str]:
    """The Odoo models the user may export : the tables of HIS store."""
    return sorted(store)


def model_ods(
    store: dict,
    model: str,
    predicates: list,
    *,
    user_id: int,
    db: str,
) -> tuple[str, bytes, str]:
    """The .ods of one Odoo model : `(filename, bytes, note)`, in one sheet.

    `store` is the store of THE USER : the file holds the rows and columns he may read,
    narrowed by the `predicates` of the panel. The ids of the relations (the columns
    ending with `_`) are left out : their names say the same thing. `note` says when
    the rows were cut at `kt.config` [explore] ods_max_rows (50 000 by default).
    """
    if model not in store:
        raise PermissionError(f"{model} : no rows you may read")
    max_rows = config.ods_max_rows()
    # the filters of the panel first : they may read the ids left out below
    rows = filter_df(store[model].lazy(), predicates)
    rows = rows.select([c for c in rows.collect_schema() if not c.endswith("_")])
    total = rows.select(pl.len()).collect().item()
    df = rows.head(max_rows).collect()
    note = f"first {max_rows} of {total} rows" if total > max_rows else ""
    data = write_ods([(model, df)])
    logger.info(
        "ods : %s",
        json.dumps(
            {
                "db": db,
                "user_id": user_id,
                "model": model,
                "rows": df.height,
                "total": total,
                "bytes": len(data),
            }
        ),
    )
    return f"kpiten-{db}-{model}.ods".replace(" ", "_"), data, note
