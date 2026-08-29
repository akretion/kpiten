import logging
from typing import Any
from marimo_kpiten.helpers import client_hooks  # noqa: F401
from marimo_kpiten.helpers.hooks import apply_df, apply_union_old
from marimo_kpiten.services.df_storage import DF_META
from marimo_kpiten.services.df_storage import DFStorage as df_store
from marimo_kpiten.services.df_style_engine import DFStyleEngine
import polars as pl
import marimo as mo
import json
import plotly.express as px

logger = logging.getLogger(__name__)


def _date_filtered(df, full_predicates):
    """Apply the date predicates when the df has a create_date column."""
    if df.get_column("create_date", default=None) is not None:
        return df.filter(full_predicates)
    return df


def _agg(source, group_col, agg_col, agg_fn):
    if agg_fn == "sum":
        return source.group_by(group_col).agg(pl.col(agg_col).sum())
    if agg_fn == "count":
        return source.group_by(group_col).agg(pl.col(agg_col).count())
    return source


def dataframe_case(
    used_df: pl.DataFrame,
    df_wt: dict[str, DF_META | list[Any]],
    transform: dict[str, Any],
    exec_context_list: list,
    full_predicates: list[bool],
):
    used_df_label = df_wt["df_meta"]["table"]  # type: ignore

    used_df = apply_df(used_df_label, used_df)

    del_action = transform["delete_this"]
    editor = None

    if transform["kind"] == "data":
        first_line = transform["content"].partition("\n")[0]
        df_like = first_line.split(" ")[2]
        df_next_like = first_line.split(" ")[0]
        editor = mo.ui.code_editor(transform["content"])
        delete_button = mo.ui.button(kind="danger", label="Suppr.", on_click=del_action)
        exec_context_list.append(
            {
                "context_type": "data",
                "df": _date_filtered(used_df, full_predicates),
                "label": used_df_label,
                "editor": editor,
                "df_like": df_like,
                "style_func": DFStyleEngine.general,
                "df_next_like": df_next_like,
                "delete_button": delete_button,
            }
        )


def card_case(
    used_df: pl.DataFrame,
    transform: dict[str, Any],
    exec_context_list: list,
    full_predicates: list[pl.Expr],
):
    card_json = json.loads(transform["content"])
    try:
        df = _date_filtered(used_df, full_predicates).sql(
            f'SELECT count(id) FROM self WHERE {card_json.get("where")}'
        )
        if df.is_empty():
            mo.stop(True)
        exec_context_list.append(
            {
                "context_type": "card",
                "label": transform.get("name"),
                "value": df.to_dict()["id"][0],
            }
        )
    except Exception as err:
        logger.error(
            "Could not load card %s. Please check your spelling, "
            "and whether you have the rights to query",
            transform.get("name"),
        )
        logger.error("full error :\n%s", err)


def union_case(transform: dict[str, Any], exec_context_list: list, full_predicates):
    union_json = json.loads(transform["content"])
    label = transform.get("name")
    union_model = union_json["union_model"]
    mapping = union_json["mapping"]
    base_model = next(m for m in mapping if m != union_model)
    dfs = [
        _date_filtered(df_store.retrieve_df(m)["df"], full_predicates)
        .select(mapping[m].keys())
        .rename(mapping[m])
        for m in (base_model, union_model)
    ]
    result = pl.concat(dfs, how="vertical_relaxed")
    exec_context_list.append(
        {"context_type": "union", "label": label, "union_df": mo.ui.table(result)}
    )


def union_old_case(transform: dict[str, Any], exec_context_list: list, full_predicates):
    union_json = json.loads(transform["content"])
    label = transform.get("name")
    base = union_json["definition"]["model"]
    other = union_json["definition"]["union_model"]

    builder = apply_union_old(base["name"])
    if builder:
        exec_context_list.append(
            {
                "context_type": "union_old",
                "label": label,
                "union_df": builder(union_json, full_predicates, label),
            }
        )
        return

    df1 = _date_filtered(df_store.retrieve_df(base["name"])["df"], full_predicates)
    df2 = _date_filtered(df_store.retrieve_df(other["name"])["df"], full_predicates)
    df1 = df1.select(base["columns"].keys()).rename(base["columns"])
    df2 = df2.select(other["columns"].keys()).rename(other["columns"])
    result = pl.concat([df1, df2], how="vertical_relaxed")
    exec_context_list.append(
        {"context_type": "union_old", "label": label, "union_df": mo.ui.table(result)}
    )


def graph_case(
    transform: dict[str, Any], full_predicates: list[bool], exec_context_list: list
):
    graph_json = json.loads(transform["content"])
    cx = graph_json["x"]
    cy = graph_json["y"]
    df = df_store.retrieve_df(graph_json["from"])["df"]

    source = _date_filtered(df.limit(500), full_predicates)
    source = _agg(source, cy["name"], cx["name"], cx["aggregation"])
    source = _agg(source, cx["name"], cy["name"], cy["aggregation"])

    labels = {
        col: col.replace("_", " ").capitalize() for col in (cx["name"], cy["name"])
    }
    common_args = dict(x=cx["name"], y=cy["name"], labels=labels)
    chart = {"bar": px.bar, "point": px.scatter, "area": px.area}
    fig = chart.get(graph_json["graph_type"], px.bar)(source, **common_args)
    fig.update_layout(
        autosize=True,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    graph = mo.ui.plotly(figure=fig)
    delete_button = mo.ui.button(kind="danger", label="Suppr.")
    exec_context_list.append(
        {
            "context_type": "graph",
            "label": transform.get("name"),
            "graph": graph,
            "delete_button": delete_button,
        }
    )
