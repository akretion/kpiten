import marimo
import polars

from marimo_kpiten.services.df_storage import DFStorage

__generated_with = "0.23.9"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    from marimo_kpiten.services.serial import dumps

    return mo, dumps


@app.cell
def navigation(mo):
    from marimo_kpiten.helpers.ui import nav_menu

    build_nav = nav_menu("/kpi", "KPI")
    return build_nav


@app.cell(hide_code=True)
def _(mo):
    from marimo_kpiten.services.df_storage import DFStorage

    df_store = DFStorage()

    tables = df_store.list_table_names()
    no_data_found_callout = None

    if not tables:
        no_data_found_callout = mo.callout(
            "There isn't any data to work on. "
            + "Create a valid 'kpiten.config' record in Odoo.",
            kind="warn",
        )

    return df_store, no_data_found_callout, tables


@app.cell
def app_style():
    from marimo_kpiten.helpers.ui import style_html

    style_html()
    return


@app.cell
def no_data_found(mo, no_data_found_callout):
    from marimo_kpiten.helpers.ui import no_data

    no_data(mo, no_data_found_callout)
    return


@app.cell
def _get_config_model():
    """
    utilise odoorpc pour récupérer env['kpiten.config.line']
    """
    from marimo_kpiten.common import _get_config_model

    config_model = _get_config_model()
    return (config_model,)


@app.cell
def panel_selection(mo):
    from marimo_kpiten.common import _get_panel_model
    from marimo_kpiten.helpers.ui import select as _select
    from marimo_kpiten.services.config import load_panels

    panel_name_to_id = {}
    panels = []
    try:
        panels = load_panels(_get_panel_model())
        panel_name_to_id = {d["name"]: d["id"] for d in panels}
    except Exception:
        pass
    panel_selector = _select(
        [d["name"] for d in panels],
        value=[panels[0]["name"]] if panels else None,
    )
    panel_ui = mo.vstack([mo.md("Panel"), panel_selector]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    return panel_selector, panel_name_to_id, panel_ui


@app.cell
def display_header(panel_ui, mo: marimo, stn_ui, build_nav, ts_ui):
    mo.hstack(
        [
            mo.hstack([mo.md("## Build • "), stn_ui, ts_ui, panel_ui]).style(
                {"max-width": "fit-content"}
            ),
            mo.hstack([build_nav]).style({"max-width": "fit-content"}),
        ],
        justify="space-between",
    )


@app.cell
def select_transformation_to_make(mo: marimo):
    from marimo_kpiten.helpers.ui import select as _select

    transformation_selector_label = mo.md("What to build ?")
    transformation_selector = _select(
        ["graph", "dataframe", "card", "union"], ["dataframe"]
    )

    ts_ui = mo.vstack([transformation_selector_label, transformation_selector]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    return (ts_ui, transformation_selector)


@app.cell
def select_df_to_build(mo: marimo, tables):
    from marimo_kpiten.helpers.ui import select as _select

    selected_model_label = mo.md("Select a model")
    selected_model = _select(tables)

    stn_ui = mo.vstack([selected_model_label, selected_model]).style(
        {"max-width": "fit-content", "color": "white"}
    )
    return (selected_model, stn_ui)


@app.cell
def display_selected_table(df_store, mo, selected_model):
    page_title = mo.md("# Create KPIs")
    display_title = mo.md("## No table selected")
    build_df = mo.md("> Select a table to start building KPIs.")
    d = None
    if len(selected_model.value) >= 1:
        sanitized_tbn = selected_model.value[0].replace(".", " ").capitalize()
        df_info = df_store.retrieve_df(selected_model.value[0])
        if df_info:
            display_title = mo.md(f"## Build Dataframes with **{sanitized_tbn}**")
            d = df_info["df"]
            build_df = mo.ui.dataframe(d)
    selected_table_ui = mo.vstack([page_title, display_title, build_df])
    return d, sanitized_tbn


@app.cell
def show_selected_table(mo, transformation_selector, selected_table_ui):
    mo.stop(transformation_selector.value[0] != "dataframe")
    selected_table_ui


@app.cell
def code_input(d, mo: marimo, transformation_selector):
    """
    code_input
    ---
    Affiche la zone de texte appelée "Paste code"
    """
    mo.stop(transformation_selector.value[0] != "dataframe")
    mo.stop(type(d) is type(None))
    python_text = mo.ui.code_editor(language="python")
    df_name = mo.ui.text(placeholder="My Kpi")
    mo.vstack(
        [
            mo.md("## Paste Code").style({"color": "white"}),
            python_text,
            df_name,
        ]
    )
    return (python_text, df_name)


@app.cell
def save_code_input(d, mo, transformation_selector):
    """
    save_code_input
    ---
    Affiche le bouton "Save to Kpiten"
    """
    mo.stop(transformation_selector.value[0] != "dataframe")
    mo.stop(type(d) is type(None))
    save = mo.ui.run_button(label="Save code to Kpiten")
    save
    return (save,)


@app.cell
def store_df_code(
    config_model,
    panel_name_to_id,
    panel_selector,
    mo,
    python_text,
    df_name,
    save,
    selected_model,
    transformation_selector,
):
    """
    store_df_code
    ---
    Stocke la transformation de dataframe via odoorpc.
    """
    mo.stop(transformation_selector.value[0] != "dataframe")
    mo.stop(not python_text.value or not save.value or len(selected_model.value) < 1)
    from marimo_kpiten.services.config import create_line as _create_line

    storedf_message = f"Successfully stored dataframe. Visit KPI's **{selected_model.value[0]}** section to see it !"
    storedf_kind = "success"
    if not python_text.value or python_text.value == "":
        storedf_message = f'Please fill in the "**Paste code**" field with python code from dataframe transformation.'
        storedf_kind = "warn"
    record = _create_line(
        config_model,
        selected_model.value[0],
        python_text.value,
        "data",
        name=df_name.value,
        panel_id=(
            panel_name_to_id.get(panel_selector.value[0]) if panel_selector.value else None
        ),
    )
    if not record:
        storedf_message = f"An error occured, please try again."
        storedf_kind = "error"
    mo.md(storedf_message).callout(kind=storedf_kind)
    return


@app.cell
def build_graph_form(d, mo: marimo, sanitized_tbn, transformation_selector):
    mo.stop(transformation_selector.value[0] != "graph")
    mo.stop(type(d) is type(None))

    from marimo_kpiten.helpers.graph_suggest import (
        classify_columns,
        suggest_aggregation,
        suggest_graph_type,
        suggest_name,
        suggest_x,
        suggest_y,
    )

    roles = classify_columns(d)
    x_options = roles["date"] + roles["dimension"]
    y_options = roles["measure"]
    sx = suggest_x(d)
    sy = suggest_y(d)

    type_of_graph_select = mo.ui.dropdown(
        options=["bar", "point", "area"], value=suggest_graph_type(d, sx)
    )
    name_input = mo.ui.text(
        placeholder="Graph's name...", value=suggest_name(sx, sy)
    )
    column_x_select = mo.ui.dropdown(options=x_options, value=sx)
    column_x_aggregation = mo.ui.dropdown(
        options=["none", "count", "sum"], value="none"
    )
    column_y_select = mo.ui.dropdown(options=y_options, value=sy)
    column_y_aggregation = mo.ui.dropdown(
        options=["none", "count", "sum"],
        value=suggest_aggregation(d, sy) if sy else "count",
    )

    create_button = mo.ui.run_button(kind="neutral", label="Create")

    form = {
        "label": name_input,
        "graph_type": type_of_graph_select,
        "x": {
            "name": column_x_select,
            "aggregation": column_x_aggregation,
        },
        "y": {
            "name": column_y_select,
            "aggregation": column_y_aggregation,
        },
    }

    from marimo_kpiten.helpers.graph_form_ui import graph_form_ui

    graph_form_ui(
        sanitized_tbn,
        name_input,
        type_of_graph_select,
        column_x_select,
        column_x_aggregation,
        column_y_select,
        column_y_aggregation,
        create_button,
    )

    return (
        create_button,
        form,
        type_of_graph_select,
        column_x_select,
        column_x_aggregation,
        column_y_select,
        column_y_aggregation,
    )


@app.cell
def graph_preview(
    column_x_aggregation,
    column_x_select,
    column_y_aggregation,
    column_y_select,
    d,
    mo,
    transformation_selector,
    type_of_graph_select,
):
    mo.stop(transformation_selector.value[0] != "graph")
    mo.stop(type(d) is type(None))

    import plotly.express as px
    import polars as pl

    x = column_x_select.value
    y = column_y_select.value
    output = mo.md(
        "Choisis une colonne X et une colonne Y pour voir l'aperçu."
    ).callout("info")
    if x and y:
        def _agg(source, group_col, agg_col, agg_fn):
            if agg_fn == "sum":
                return source.group_by(group_col).agg(pl.col(agg_col).sum())
            if agg_fn == "count":
                return source.group_by(group_col).agg(pl.col(agg_col).count())
            return source

        source = d.limit(500)
        source = _agg(source, y, x, column_x_aggregation.value or "none")
        source = _agg(source, x, y, column_y_aggregation.value or "none")

        labels = {col: col.replace("_", " ").capitalize() for col in (x, y)}
        chart = {"bar": px.bar, "point": px.scatter, "area": px.area}
        fig = chart.get(type_of_graph_select.value or "bar", px.bar)(
            source, x=x, y=y, labels=labels
        )
        fig.update_layout(autosize=True, margin=dict(l=20, r=20, t=40, b=20))
        output = mo.ui.plotly(figure=fig)

    return output


@app.cell
def save_graph_form_data(
    create_button,
    dumps,
    form,
    config_model,
    panel_name_to_id,
    panel_selector,
    mo,
    selected_model,
    transformation_selector,
):
    mo.stop(transformation_selector.value[0] != "graph")
    mo.stop(not create_button.value)

    from marimo_kpiten.services.config import create_line as _create_line

    form_record = _create_line(
        config_model,
        selected_model.value[0],
        dumps(
            {
                "graph_type": form["graph_type"].value,
                "from": selected_model.value[0],
                "x": {
                    "name": form["x"]["name"].value,
                    "aggregation": form["x"]["aggregation"].value,
                },
                "y": {
                    "name": form["y"]["name"].value,
                    "aggregation": form["y"]["aggregation"].value,
                },
            }
        ),
        "graph",
        name=form["label"].value,
        panel_id=(
            panel_name_to_id.get(panel_selector.value[0]) if panel_selector.value else None
        ),
    )
    message = f"Successfully stored graph. Visit KPI's **{selected_model.value[0]}** section to see it !"
    callout_kind = "success"
    if not form_record:
        message = "Couldn't store graph, please try again later."
        callout_kind = "error"

    mo.md(
        message,
    ).callout(kind=callout_kind)
    return


@app.cell
def build_card(d, mo, sanitized_tbn, transformation_selector):
    mo.stop(transformation_selector.value[0] != "card")
    mo.stop(type(d) is type(None))
    card_cell_title = mo.md(f"## Build a card from **{sanitized_tbn}**")
    card_cell_desc = mo.md(
        "> You provide an SQL query that generates an interesting number / short "
        "information about your company, and the result will be displayed as a "
        "KPI Card in the `KPI` section."
    )
    card_name = mo.ui.text(placeholder="Name")
    card_sql = mo.ui.code_editor(
        placeholder="state IN ('draft', 'sent')", language="sql"
    )
    save_card_btn = mo.ui.run_button(kind="neutral", label="Save")

    mo.vstack([card_cell_title, card_cell_desc, card_name, card_sql, save_card_btn])
    return card_name, card_sql, save_card_btn


@app.cell
def save_card(
    card_name,
    dumps,
    card_sql,
    config_model,
    panel_name_to_id,
    panel_selector,
    mo,
    sanitized_tbn,
    save_card_btn,
    selected_model,
    transformation_selector,
):
    mo.stop(transformation_selector.value[0] != "card")
    mo.stop(not save_card_btn.value)

    from marimo_kpiten.services.config import create_line as _create_line

    card_record = _create_line(
        config_model,
        selected_model.value[0],
        dumps(
            {
                "where": card_sql.value,
                "from": selected_model.value[0],
            }
        ),
        "card",
        name=card_name.value,
        panel_id=(
            panel_name_to_id.get(panel_selector.value[0]) if panel_selector.value else None
        ),
    )

    save_card_message = f"Successfully stored card. Visit the **{sanitized_tbn}** section in `KPI` to see it !"
    save_card_kind = "success"
    if not card_record:
        save_card_message = "Couldn't store card, please try again later."
        save_card_kind = "error"
    mo.md(save_card_message).callout(kind=save_card_kind)
    return


@app.cell
def union_tables_selectors(mo: marimo, transformation_selector, tables, sanitized_tbn):
    from marimo_kpiten.helpers.ui import select as _select

    mo.stop(transformation_selector.value[0] != "union")

    union_name = mo.ui.text(placeholder="Union name")
    table2_sel_label = mo.md(f"Table 2 (to make an union with {sanitized_tbn})")
    table2_selector = _select(tables)
    mo.hstack(
        [
            mo.vstack([union_name, table2_sel_label, table2_selector]).style(
                {"color": "white"}
            )
        ]
    ).style({"color": "white"})

    return (table2_selector, union_name)


@app.cell
def union_columns_selectors(
    mo: marimo,
    transformation_selector,
    table2_selector,
    d: polars.DataFrame,
    df_store: DFStorage,
    sanitized_tbn,
):
    mo.stop(transformation_selector.value[0] != "union")
    mo.stop(len(table2_selector.value) == 0)

    union_df = df_store.retrieve_df(table2_selector.value[0])["df"]
    selected_df_ucols_selector = mo.ui.multiselect(options=d.columns)
    union_df_cols_selector = mo.ui.multiselect(options=union_df.columns)

    mo.hstack(
        [
            mo.vstack(
                [
                    mo.md(f"Cols of {sanitized_tbn}"),
                    selected_df_ucols_selector,
                ]
            ).style({"color": "white"}),
            mo.vstack(
                [
                    mo.md(f"Cols of {table2_selector.value[0]}"),
                    union_df_cols_selector,
                ]
            ).style({"color": "white"}),
        ]
    )
    return (selected_df_ucols_selector, union_df_cols_selector, union_df)


@app.cell
def show_ucolumn_types(
    mo: marimo,
    selected_df_ucols_selector,
    transformation_selector,
    union_df_cols_selector,
):
    mo.stop(transformation_selector.value[0] != "union")
    mo.stop(
        len(union_df_cols_selector.value) == 0
        or len(selected_df_ucols_selector.value) == 0
    )

    save_union_button = mo.ui.run_button(label="Save")
    mo.hstack(
        [
            mo.vstack([mo.md("Base cols"), selected_df_ucols_selector.value]),
            mo.vstack([mo.md("Union cols"), union_df_cols_selector.value]),
            save_union_button,
        ]
    ).style({"color": "white"})
    return save_union_button


@app.cell
def save_union(
    config_model,
    dumps,
    mo,
    sanitized_tbn,
    save_union_button,
    selected_df_ucols_selector,
    selected_model,
    table2_selector,
    transformation_selector,
    union_df_cols_selector,
    union_name,
    panel_name_to_id,
    panel_selector,
):
    from marimo_kpiten.services.config import create_line as _create_line

    mo.stop(transformation_selector.value[0] != "union")
    mo.stop(not save_union_button.value)

    base_model = selected_model.value[0]
    union_model = table2_selector.value[0]
    base_cols = selected_df_ucols_selector.value
    union_cols = union_df_cols_selector.value
    mapping = {
        base_model: {c: c for c in base_cols},
        union_model: dict(zip(union_cols, base_cols)),
    }
    union_record = _create_line(
        config_model,
        base_model,
        dumps({"union_model": union_model, "mapping": mapping}),
        "union",
        name=union_name.value,
        panel_id=(
            panel_name_to_id.get(panel_selector.value[0]) if panel_selector.value else None
        ),
    )

    union_message = f"Successfully stored union. Visit the **{sanitized_tbn}** section in `KPI` to see it !"
    union_kind = "success"
    if not union_record:
        union_message = "Couldn't store union, please try again later."
        union_kind = "error"
    mo.md(union_message).callout(kind=union_kind)
    return


if __name__ == "__main__":
    app.run()
