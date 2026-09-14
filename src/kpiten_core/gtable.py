"""great_tables styling shared by the dashboard apps (dark palettes)."""

import polars as pl
from great_tables import GT


def gt_table(df: pl.DataFrame, palette: dict) -> GT:
    """great_tables table adapted to the app theme palette."""
    return (
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
