import marimo

__generated_with = "0.23.4"
app = marimo.App(width="medium")


@app.cell()
def navigation(mo: marimo):
    mo.nav_menu({"/build": "Create", "/kpi": "KPI"})


@app.cell
def _():
    import marimo as mo
    from pathlib import Path
    from marimo_kpiten.services.df_file_storage_service import DFStorageService

    df_store = DFStorageService()

    # using tables in generated
    table_names = []
    to_display = []

    generated = Path("../generated")
    res = generated.iterdir()
    for file in res:
        table_names.append(file.name)

    for name in table_names:
        df_info = df_store.retrieve_df(name)
        df_name = df_info[1]
        df_data = df_info[4]
        vs = mo.vstack(
            [
                mo.md(f'# {df_name.replace("_", " ").capitalize()}'),
                mo.md("---"),
                mo.ui.dataframe(df_data),
            ]
        )
        to_display.append(vs)

    display = mo.vstack(to_display)
    display
    return


if __name__ == "__main__":
    app.run()
