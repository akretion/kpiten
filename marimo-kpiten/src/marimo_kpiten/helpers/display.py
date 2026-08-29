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
        table_html = mo.md(f"**Error**  {ctx['editor'].value}").callout("warn")
    else:
        table_html = mo.ui.table(result_df)
        if render_opt == "Reporting":
            table_html = ctx["style_func"](result_df.limit(20)).as_raw_html()
            logger.debug(table_html)
    delete_html = ctx["delete_button"].text
    return f"""
        <div style="display:flex; flex-flow:column; width: {data_t_width}; min-width:300px; gap:0.5rem; padding:0.5rem; box-sizing:border-box">
            <div style="overflow:scroll">{table_html}</div>
            {delete_html}
        </div>
    """


def union_old_block(ctx, mo):
    return mo.vstack(
        [
            mo.md(f"## {ctx['label']}").style({"color": "white"}),
            ctx["union_df"],
        ]
    )


def graph_block(ctx, mo):
    graph_html = ctx["graph"].text
    delete_html = ctx["delete_button"].text
    return f"""
        <div style="display:flex; flex-flow:column; width:80vw; min-width:400px; gap:0.5rem; padding:0.5rem; box-sizing:border-box">
            <h2 style="margin:0">{ctx['label']}</h2>
            {graph_html}
            {delete_html}
        </div>
    """


def layout_html(blocks, layout):
    common = 'div style="display:flex; flex-flow'
    flow = (
        ":column; width:100%; gap:1rem"
        if layout == "Serial"
        else ":row wrap; gap:1rem; width:200%"
    )
    inner = "".join([f'<{common}{flow}">{b}</div>' for b in blocks])
    return f'<{common}:column; width:100%; gap:2rem">{inner}</div>'
