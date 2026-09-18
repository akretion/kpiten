"""great_tables styling shared by the dashboard apps (dark palettes)."""

import polars as pl
from great_tables import GT

from kpiten_core import links


def gt_table(df: pl.DataFrame, palette: dict) -> GT:
    """great_tables table adapted to the app theme palette.

    A column of `[label](url)` values is drawn as links to Odoo (`links`)."""
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
    linked = links.link_columns(df)
    if linked:
        table = table.fmt(
            lambda value: links.link_html(value, palette.get("accent")), columns=linked
        )
    return table
