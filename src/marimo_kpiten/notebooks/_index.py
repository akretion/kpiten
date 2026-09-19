import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="Marimo notebook")


@app.cell
def _():
    import html

    import marimo as mo

    from marimo_kpiten.analyses import ANALYSES

    return ANALYSES, html, mo


@app.cell
def _(ANALYSES, html, mo):
    _cards = "".join(
        f'<a href="/dashboard/{key}/" title="{html.escape(a["about"], quote=True)}" '
        'style="display:block;width:16rem;padding:1rem 1.2rem;border:1px solid #ddd;'
        'border-radius:.6rem;text-decoration:none;color:inherit">'
        f'<div style="font-size:2rem">{a["icon"]}</div>'
        f'<div style="font-weight:600;margin-top:.4rem">{html.escape(a["title"])}</div>'
        f'<div style="opacity:.7;font-size:.85rem;margin-top:.2rem">{html.escape(a["about"])}</div>'
        "</a>"
        for key, a in ANALYSES.items()
    )
    mo.vstack(
        [
            # the title, and the logo of marimo (served by marimo itself) on the right
            mo.hstack(
                [
                    mo.md("# Marimo notebook"),
                    mo.Html(
                        '<img src="/dashboard/logo.png" alt="marimo" '
                        'title="Made with marimo" style="height:28px;width:auto">'
                    ),
                ],
                justify="space-between",
                align="center",
            ),
            mo.Html(
                f'<div style="display:flex;flex-wrap:wrap;gap:1rem">{_cards}</div>'
            ),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
