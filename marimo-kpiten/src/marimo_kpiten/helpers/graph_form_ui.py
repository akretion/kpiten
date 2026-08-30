import marimo as mo


def graph_form_ui(
    sanitized_tbn: str,
    name_input: mo.ui.text,
    type_of_graph_select: mo.ui.dropdown,
    column_x_select: mo.ui.dropdown,
    column_x_aggregation: mo.ui.dropdown,
    column_y_select: mo.ui.dropdown,
    column_y_aggregation: mo.ui.dropdown,
    create_button: mo.ui.run_button,
):
    return mo.vstack(
        [
            mo.md(f"## Build a Graph from **{sanitized_tbn}**").style(
                {"color": "white"}
            ),
            mo.vstack([mo.md("Name"), name_input]).style({"color": "white"}),
            mo.vstack(
                [mo.md("Graph type"), type_of_graph_select]
            ).style({"color": "white"}),
            mo.md("### X — date ou catégorie").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("X column"), column_x_select]),
                    mo.vstack([mo.md("X aggregation"), column_x_aggregation]),
                ]
            ).style({"color": "white"}),
            mo.md("### Y — valeur à agréger").style({"color": "white"}),
            mo.hstack(
                [
                    mo.vstack([mo.md("Y column"), column_y_select]),
                    mo.vstack([mo.md("Y aggregation"), column_y_aggregation]),
                ]
            ).style({"color": "white"}),
            create_button,
        ]
    ).style({"max-width": "50%"})