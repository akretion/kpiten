import logging
from typing import Any
from marimo_kpiten.helpers import client_hooks  # noqa: F401
from marimo_kpiten.helpers.hooks import apply_df, apply_union_old
from marimo_kpiten.services.df_storage import DF_META
from marimo_kpiten.services.df_storage import DFStorage as df_store
from marimo_kpiten.services.df_style_engine import DFStyleEngine
import polars as pl
import marimo as mo
from marimo_kpiten.services.serial import loads
from marimo_kpiten.helpers.pivot_suggest import apply_monthly, is_date
from marimo_kpiten.services.i18n import t
import plotly.express as px

logger = logging.getLogger(__name__)


def _filtered(df, predicates):
    """Apply the predicates whose columns exist on the df."""
    applicable = [
        p for p in predicates if all(col in df.columns for col in p.meta.root_names())
    ]
    if applicable:
        return df.filter(applicable)
    return df


def _agg(source, group_col, agg_col, agg_fn):
    if agg_fn == "sum":
        return source.group_by(group_col).agg(pl.col(agg_col).sum())
    if agg_fn == "count":
        return source.group_by(group_col).agg(pl.col(agg_col).count())
    return source


def _delete_button(on_click):
    if not on_click:
        return None
    return mo.ui.button(
        kind="danger", label="🗑️", tooltip=t("Supprimer"), on_click=on_click
    )


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
        delete_button = _delete_button(del_action)
        exec_context_list.append(
            {
                "context_type": "data",
                "df": _filtered(used_df, full_predicates),
                "label": transform.get("name") or used_df_label,
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
    card_json = loads(transform["content"])
    try:
        df = _filtered(used_df, full_predicates).sql(
            f'SELECT count(id) FROM self WHERE {card_json.get("where")}'
        )
        if df.is_empty():
            mo.stop(True)
        exec_context_list.append(
            {
                "context_type": "card",
                "label": transform.get("name"),
                "value": df.to_dict()["id"][0],
                "delete_button": _delete_button(transform["delete_this"]),
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
    union_json = loads(transform["content"])
    label = transform.get("name")
    union_model = union_json["union_model"]
    mapping = union_json["mapping"]
    base_model = next(m for m in mapping if m != union_model)
    dfs = [
        _filtered(df_store.retrieve_df(m)["df"], full_predicates)
        .select(mapping[m].keys())
        .rename(mapping[m])
        for m in (base_model, union_model)
    ]
    result = pl.concat(dfs, how="vertical_relaxed")
    exec_context_list.append(
        {
            "context_type": "union",
            "label": label,
            "union_df": mo.ui.table(result),
            "delete_button": _delete_button(transform["delete_this"]),
        }
    )


def union_old_case(transform: dict[str, Any], exec_context_list: list, full_predicates):
    union_json = loads(transform["content"])
    label = transform.get("name")
    base = union_json["definition"]["model"]
    other = union_json["definition"]["union_model"]

    builder = apply_union_old(base["name"])
    delete_button = _delete_button(transform["delete_this"])
    if builder:
        exec_context_list.append(
            {
                "context_type": "union_old",
                "label": label,
                "union_df": builder(union_json, full_predicates, label),
                "delete_button": delete_button,
            }
        )
        return

    df1 = _filtered(df_store.retrieve_df(base["name"])["df"], full_predicates)
    df2 = _filtered(df_store.retrieve_df(other["name"])["df"], full_predicates)
    df1 = df1.select(base["columns"].keys()).rename(base["columns"])
    df2 = df2.select(other["columns"].keys()).rename(other["columns"])
    result = pl.concat([df1, df2], how="vertical_relaxed")
    exec_context_list.append(
        {
            "context_type": "union_old",
            "label": label,
            "union_df": mo.ui.table(result),
            "delete_button": delete_button,
        }
    )


def pivot_case(used_df, transform, exec_context_list, full_predicates):
    pivot_json = loads(transform["content"])
    index = pivot_json["index"]
    column = pivot_json["column"]
    measure = pivot_json["measure"]
    aggregation = pivot_json.get("aggregation", "sum")
    monthly = pivot_json.get("monthly", False)

    df = _filtered(used_df, full_predicates)
    if monthly and column and is_date(df, column):
        df = apply_monthly(df, column)
    elif monthly and index and is_date(df, index):
        df = apply_monthly(df, index)

    result = df.pivot(
        index=index,
        on=column,
        values=measure,
        aggregate_function=aggregation,
    )
    exec_context_list.append(
        {
            "context_type": "pivot",
            "label": transform.get("name"),
            "pivot_df": mo.ui.table(result),
            "delete_button": _delete_button(transform["delete_this"]),
        }
    )


def graph_case(
    transform: dict[str, Any], full_predicates: list[bool], exec_context_list: list
):
    graph_json = loads(transform["content"])
    cx = graph_json["x"]
    cy = graph_json["y"]
    df = df_store.retrieve_df(graph_json["from"])["df"]

    source = _filtered(df.limit(500), full_predicates)
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
    delete_button = _delete_button(transform["delete_this"])
    exec_context_list.append(
        {
            "context_type": "graph",
            "label": transform.get("name"),
            "graph": graph,
            "delete_button": delete_button,
        }
    )
