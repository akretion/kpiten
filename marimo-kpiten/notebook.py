import marimo

__generated_with = "0.22.5"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Simple Notebook
    """)
    return


@app.cell(hide_code=True)
def _(mo, slider):
    mo.md(rf"""
     slider value : **{slider.value}**
    """)
    return


@app.cell
def _(mo):
    slider = mo.ui.slider(start=0, stop=10, step=2)
    slider
    return (slider,)


if __name__ == "__main__":
    app.run()
