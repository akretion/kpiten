import marimo

__generated_with = "0.22.5"
app = marimo.App(width="medium")

@app.cell
def _():
    import marimo as mo
    import polars as pl
    from main import DATAFRAMES

    print(DATAFRAMES)

    for df in DATAFRAMES:
        df
    return


if __name__ == "__main__":
    app.run()
