"""great_tables styling shared by the dashboard apps (dark palettes)."""

import re

import polars as pl
from great_tables import GT

from kpiten_core import links, numfmt

# a table that can be drilled into : its rows are clickable (see `tiles.exec_drill`)
DRILL_CSS = """
.tile.drillable .gt_table tbody tr { cursor: pointer; }
.tile.drillable .gt_table tbody tr:hover { filter: brightness(1.25); }
"""

# numbers that are not quantities : ids and calendar parts stay as they are
NOT_A_QUANTITY_RE = re.compile(r"(?i)(^|[\s._-])(id|year|quarter|month|week|day)s?$")


def number_columns(df: pl.DataFrame) -> tuple[list[str], list[str]]:
    """The (integer, decimal) columns of quantities : those are formatted."""
    integers, decimals = [], []
    for name, dtype in df.schema.items():
        if dtype == pl.Boolean or not dtype.is_numeric():
            continue
        if NOT_A_QUANTITY_RE.search(name):
            continue
        (integers if dtype.is_integer() else decimals).append(name)
    return integers, decimals


def gt_table(df: pl.DataFrame, palette: dict) -> GT:
    """great_tables table adapted to the app theme palette.

    A column of `[label](url)` values is drawn as links to Odoo (`links`) ; the
    quantities are right aligned, thousands separated, with 2 decimals for the
    decimal ones (`numfmt`)."""
    table = (
        GT(df)
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
    for columns, digits in ((integers, 0), (decimals, 2)):
        if columns:
            table = table.fmt(
                lambda value, digits=digits: (
                    "" if value is None else numfmt.format_number(value, digits)
                ),
                columns=columns,
            ).cols_align("right", columns=columns)
    linked = links.link_columns(df)
    if linked:
        table = table.fmt(
            lambda value: links.link_html(value, palette.get("accent")), columns=linked
        )
    return table
