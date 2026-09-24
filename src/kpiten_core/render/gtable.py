"""A table as great_tables draws it, in the colors of the theme (the `render` extra)."""

import logging

import polars as pl
from great_tables import GT, loc, style

from kpiten_core import links, numfmt
from kpiten_core.numfmt import number_columns

logger = logging.getLogger(__name__)

# a table that can be drilled into : its rows are clickable (see `tiles.exec_drill`)
DRILL_CSS = """
.tile.drillable .gt_table tbody tr { cursor: pointer; }
.tile.drillable .gt_table tbody tr:hover { filter: brightness(1.25); }
"""


def gt_table(df: pl.DataFrame, palette: dict, drawing: dict | None = None) -> GT:
    """great_tables table adapted to the app theme palette.

    A column of `[label](url)` values is drawn as links to Odoo (`links`) ; the
    quantities are right aligned, thousands separated, the decimal ones rounded
    to the unit unless they are below 10 (`numfmt.format_quantity`).
    `drawing` is the `[table]` of the tile (`TileResult.meta["table"]`, see
    `tiles._pivot_table`) : formats, « Total » row, heatmap, note, options."""
    drawing = drawing or {}
    if drawing:  # a SQL sum is a Decimal : great_tables colors floats only (heatmap)
        decimal = [c for c, t in df.schema.items() if isinstance(t, pl.Decimal)]
        if decimal:
            df = df.with_columns(pl.col(decimal).cast(pl.Float64))
    rows = df.height  # the rows of data : the « Total » row comes after them
    linked = links.link_columns(df)  # on the data : « Total » is not a link
    if drawing.get("totals"):
        total = pl.DataFrame([drawing["totals"]], schema=df.schema, strict=False)
        df = pl.concat([df, total], how="vertical_relaxed")
    stub = df.columns[0] if drawing and drawing.get("stub", True) else None
    table = (
        GT(df, rowname_col=stub)
        .tab_options(
            table_background_color=palette["surface_hex"],
            table_font_color=palette["text"],
            column_labels_background_color=palette["thead"],
            column_labels_border_lr_color=palette["border_hex"],
            column_labels_border_bottom_color=palette["border_hex"],
            table_body_hlines_color=palette["row_line"],
            table_border_top_color=palette["border_hex"],
            table_border_bottom_color=palette["border_hex"],
            table_font_size="13px",
        )
        .cols_align("left")
    )
    integers, decimals = number_columns(df)
    if drawing:
        table = _formats(table, df, drawing, integers + decimals)
    else:
        for columns, show in (
            (integers, numfmt.format_number),
            (decimals, numfmt.format_quantity),
        ):
            if columns:
                table = table.fmt(
                    lambda value, show=show: "" if value is None else show(value),
                    columns=columns,
                ).cols_align("right", columns=columns)
    if linked:
        table = table.fmt(
            lambda value: links.link_html(value, palette.get("accent")), columns=linked
        )
    if stub:  # the header of the row headers : great_tables leaves it empty
        table = table.tab_stubhead(label=stub)
    return _drawing(table, df, palette, drawing, rows) if drawing else table


def _formats(table: GT, df: pl.DataFrame, drawing: dict, numbers: list[str]) -> GT:
    """The cells in the `format` / `decimals` of `[table]`, or of its `columns`."""
    per_column = drawing.get("columns") or {}
    for column in numbers:
        cell = {**drawing, **per_column.get(column, {})}
        fmt, digits = cell.get("format", "number"), cell.get("decimals", 0)
        table = table.fmt(
            lambda value, fmt=fmt, digits=digits: numfmt.format_value(
                value, fmt, digits
            ),
            columns=[column],
        )
    return table.cols_align("right", columns=numbers) if numbers else table


def _drawing(table: GT, df: pl.DataFrame, palette: dict, drawing: dict, rows: int):
    """The heatmap, the « Total » row in bold, the note and the options of `[table]`."""
    values = [c for c in drawing.get("values", []) if c in df.columns]
    if drawing.get("heatmap") and values and rows:
        table = table.data_color(
            columns=values,
            rows=list(range(rows)),
            palette=[palette["surface_hex"], palette["accent"]],
        )
    if drawing.get("totals"):
        table = table.tab_style(
            style=style.text(weight="bold"), locations=loc.body(rows=[rows])
        )
    if drawing.get("note"):
        table = table.tab_source_note(drawing["note"])
    if drawing.get("options"):
        try:
            table = table.tab_options(**drawing["options"])
        except (TypeError, ValueError):
            logger.warning("[table.options] ignored : %s", drawing["options"])
    return table
