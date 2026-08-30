import logging

from marimo_kpiten.services.sandbox import run

logger = logging.getLogger(__name__)


def data_block(ctx, data_t_width, render_opt, mo):
    try:
        result_df = run(
            ctx["editor"].value, ctx["df"], ctx["df_like"], ctx["df_next_like"]
        )
    except Exception:
        result_df = None
    if result_df is None:
        table = mo.md(f"**Error**  {ctx['editor'].value}").callout("warn")
    else:
        table = mo.ui.table(result_df)
        if render_opt == "Reporting":
            table = mo.Html(ctx["style_func"](result_df.limit(20)).as_raw_html())
            logger.debug(table)
    return mo.vstack(
        [_header(ctx, mo), table],
        gap="0.5rem",
    ).style({"width": data_t_width, "min-width": "300px"})


def _header(ctx, mo):
    items = []
    if ctx.get("delete_button"):
        items.append(ctx["delete_button"])
    items.append(mo.md(f"## {ctx['label']}").style({"color": "white"}))
    return mo.hstack(items, justify="start")


def union_block(ctx, mo):
    return mo.vstack([_header(ctx, mo), ctx["union_df"]])


def union_old_block(ctx, mo):
    return mo.vstack([_header(ctx, mo), ctx["union_df"]])


def graph_block(ctx, mo):
    return mo.vstack([_header(ctx, mo), ctx["graph"]], gap="0.5rem").style(
        {"width": "80vw", "min-width": "400px"}
    )


def layout_blocks(blocks, layout, mo):
    if layout == "Serial":
        container = mo.vstack(blocks, gap="1rem")
    else:
        container = mo.hstack(blocks, wrap=True, gap="1rem")
    return container.style({"max-width": "1200px"})
