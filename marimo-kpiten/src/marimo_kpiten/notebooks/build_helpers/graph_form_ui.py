import marimo as mo


def graph_form_ui(
    sanitized_tbn: str,
    name_input: mo.ui.text,
    type_of_graph_select: mo.ui.multiselect,
    column_x_select: mo.ui.multiselect,
    column_x_aggregation: mo.ui.multiselect,
    column_y_select: mo.ui.multiselect,
    column_y_aggregation: mo.ui.multiselect,
    create_button: mo.ui.run_button,
):
    return mo.vstack(
        [
            mo.md(f"## Build a Graph from **{sanitized_tbn}**").style(
                {"color": "white"}
            ),
            name_input,
            mo.hstack(
                [mo.md("Graph type").style({"color": "white"}), type_of_graph_select],
                justify="start",
            ).style({"color": "white"}),
            mo.md("### X Axis").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("X Column"), column_x_select]),
                    mo.vstack([mo.md("X Aggregation"), column_x_aggregation]),
                ]
            ).style({"color": "white"}),
            mo.md("### Y Axis").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("Y Column"), column_y_select]),
                    mo.vstack([mo.md("Y Aggregation"), column_y_aggregation]),
                ]
            ).style({"color": "white"}),
            create_button,
        ]
    ).style({"max-width": "50%"})
