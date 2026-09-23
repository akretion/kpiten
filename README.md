# quarto-kpiten

A KpiTen plugin (pluggy hooks of `kpiten_core.hookspecs`) : a button of the dashboard
downloads the panel on screen as a PDF, with its period, its filters and the rights of
the user. The cards are a table (value, change), the tables keep their links to Odoo,
the graphs are images (kaleido). The document is Markdown rendered by
[Quarto](https://quarto.org) through Typst : no LaTeX.

`quarto-cli` brings Quarto and Typst in the venv. kaleido needs a Chrome : the one of
playwright is used when kaleido finds none (`KPITEN_CHROME` to give another).

    uv pip install -e src/quarto-kpiten   # in the venv the dashboards run in
