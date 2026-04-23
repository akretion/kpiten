import marimo

__generated_with = "0.22.5"
app = marimo.App(width="medium")

@app.cell
def __():
    import marimo as mo
    return (mo,)

@app.cell
def _(mo):
    import polars as pl

    button = mo.ui.run_button("neutral", label="Refresh sale order")
    button
    return (button,)

@app.cell
def _(mo, button):
    mo.stop(not button.value)
    from services.df_file_storage_service import DFFileStorage

    df_fs_service = DFFileStorage()

    sales = df_fs_service.retrieve_df("sale_order")

    mo.md(f'# {sales[0]}')
    mo.ui.dataframe(sales[2])

if __name__ == "__main__":
    app.run()
