"""A table as great_tables draws it, in the colors of the theme (the `render` extra)."""

import polars as pl
from great_tables import GT

from kpiten_core import links, numfmt
from kpiten_core.numfmt import number_columns

# a table that can be drilled into : its rows are clickable (see `tiles.exec_drill`)
DRILL_CSS = """
.tile.drillable .gt_table tbody tr { cursor: pointer; }
.tile.drillable .gt_table tbody tr:hover { filter: brightness(1.25); }
"""


def gt_table(df: pl.DataFrame, palette: dict) -> GT:
    """great_tables table adapted to the app theme palette.

    A column of `[label](url)` values is drawn as links to Odoo (`links`) ; the
    quantities are right aligned, thousands separated, the decimal ones rounded
    to the unit unless they are below 10 (`numfmt.format_quantity`)."""
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
    for columns, show in (
        (integers, numfmt.format_number),
        (decimals, numfmt.format_quantity),
    ):
        if columns:
            table = table.fmt(
                lambda value, show=show: "" if value is None else show(value),
                columns=columns,
            ).cols_align("right", columns=columns)
    linked = links.link_columns(df)
    if linked:
        table = table.fmt(
            lambda value: links.link_html(value, palette.get("accent")), columns=linked
        )
    return table
