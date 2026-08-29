from typing import Any
from marimo_kpiten.services.df_storage import DF_META
from marimo_kpiten.services.df_storage import DFStorage as df_store
from marimo_kpiten.services.df_style_engine import DFStyleEngine
import polars as pl
import polars.selectors as cs
import marimo as mo
import json
from great_tables import GT, vals, style, loc
import plotly.express as px


def dataframe_case(
    used_df: pl.DataFrame,
    df_wt: dict[str, DF_META | list[Any]],
    transform: dict[str, Any],
    exec_context_list: list,
    full_predicates: list[bool],
):
    used_df_label = df_wt["df_meta"]["table"]  # type: ignore

    # CUSTOM CODE - TODO : make this kind of custom code a hook
    if used_df_label == "account.analytic.line":
        # Filtering
        used_df = used_df.filter(
            pl.col("category").eq("invoice"),
            pl.col("product_id_").is_not_null(),
            pl.col("plan_id.name").str.contains("Projet"),
            pl.col("move_line_id.display_type").eq("product"),
            pl.col("date").dt.year().eq(2026),
        )

        # Months columns
        used_df = used_df.with_columns(
            pl.col("date").dt.month().alias("mois"),
            pl.col("date").dt.year().alias("annee"),
        )

        used_df = (
            used_df.group_by(["move_id.name", "annee", "mois"])
            .agg(pl.col("amount").sum(), pl.col("price_subtotal").sum())
            .sort(by=["move_id.name"], descending=True)
        )

        month_map = {
            "1": "Janvier",
            "2": "Février",
            "3": "Mars",
            "4": "Avril",
            "5": "Mai",
            "6": "Juin",
            "7": "Juillet",
            "8": "Août",
            "9": "Septembre",
            "10": "Octobre",
            "11": "Novembre",
            "12": "Décembre",
        }

        for m in month_map.items():
            used_df = used_df.with_columns(
                pl.col("mois").cast(pl.Utf8).replace(month_map).alias("mois")
            )

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
                "df": (
                    used_df.filter(full_predicates)
                    if used_df.get_column("create_date", default=None) is not None
                    else used_df
                ),
                "label": used_df_label,
                "editor": editor,
                "df_like": df_like,
                "style_func": DFStyleEngine.general,
                "df_next_like": df_next_like,
                "delete_button": delete_button,
            }
        )


def BAN_case(
    used_df: pl.DataFrame,
    transform: dict[str, Any],
    exec_context_list: list,
    full_predicates: list[pl.Expr],
):
    BAN_json = json.loads(transform["content"])
    try:
        filtered_df = (
            used_df.filter(full_predicates)
            if used_df.get_column("create_date", default=None) is not None
            else used_df
        )
        df = filtered_df.sql(
            f'SELECT count(id) FROM self WHERE {BAN_json.get("where")}'
        )
        if df.is_empty():
            mo.stop(True)
        else:
            BAN = df.to_dict()["id"][0]
        exec_context_list.append(
            {
                "context_type": "ban",
                "label": transform.get("name") or BAN_json.get("name"),
                "BAN": BAN,
            }
        )
    except pl.exceptions.ColumnNotFoundError as err:
        print(
            f"Could not load BAN {BAN_json['name']}. Please check",
            " your spelling, and whether you have the rights to query",
        )
        print(f"full error :\n{err}")


def union_case(transform: dict[str, Any], exec_context_list: list, full_predicates):

    union_json = json.loads(transform["content"])
    base_model_df = (
        df_store.retrieve_df(union_json["definition"]["model"]["name"])["df"]
        .filter(
            pl.col("department_id").is_not_null(),
            pl.col("budget_type").is_not_null(),
        )
        .filter(full_predicates)
    )
    union_model_df = df_store.retrieve_df(
        union_json["definition"]["union_model"]["name"]
    )["df"].filter(full_predicates)

    # from marimo_kpiten.services.temp_transform_engine import TransformEngine

    # engine = TransformEngine(
    #     {"model": "account.analytic.line", "df": base_model_df},
    #     {"model": "mrp.workcenter.productivity", "df": union_model_df},from marimo_kpiten.services.temp_transform_engine import TransformEngine
    #     "./services/mixed_timesheets.rules.toml",
    # )

    # engine.run()

    union_model_df = union_model_df.with_columns(
        pl.lit("production").alias("description")
    )

    bmdf_columns = union_json["definition"]["model"]["columns"]
    umdf_columns = union_json["definition"]["union_model"]["columns"]
    base_model_df = base_model_df.select(bmdf_columns.keys())
    union_model_df = union_model_df.select(umdf_columns.keys())

    base_model_df = base_model_df.rename(bmdf_columns)
    union_model_df = union_model_df.rename(umdf_columns)

    union_model_df.with_columns(
        pl.when(pl.col("dept").is_null())
        .then(pl.lit("Production & Méthode / Production"))
        .otherwise(pl.col("dept"))
    )

    UNION_DF = pl.concat([base_model_df, union_model_df], how="vertical_relaxed")

    # --- Renaming (stays: these values are used in group_by/filter later, not just display) ---
    UNION_DF = UNION_DF.with_columns(
        pl.when(pl.col("employé") == "employee")
        .then(pl.lit("Employé entreprise"))
        .when(pl.col("employé") == "temporary")
        .then(pl.lit("Intérimaire"))
        .when(pl.col("employé").is_null())
        .then(pl.lit("Employé entreprise"))
        .when(pl.col("employé") == "contractor")
        .then(pl.lit("Sous-Traitant / Sous Contrat"))
        .otherwise(pl.col("employé"))
        .alias("employé")
    )

    UNION_DF = UNION_DF.with_columns(
        pl.when(
            (pl.col("dept") == "production")
            | (pl.col("dept") == "quality")
            | (pl.col("dept") == "availability")
            | (pl.col("dept") == "performance")
            | (pl.col("dept") == "productive")
        )
        .then(pl.lit("Production & Méthode / Production"))
        .otherwise(pl.col("dept"))
        .alias("dept")
    )

    UNION_DF = UNION_DF.with_columns(
        pl.when(pl.col("budget") == "production")
        .then(pl.lit("FAB"))
        .when(pl.col("budget") == "installation")
        .then(pl.lit("POSE"))
        .when(pl.col("budget") == "service")
        .then(pl.lit("BE"))
        .otherwise(pl.col("budget"))
        .alias("budget")
    )

    # --- Month pivot + aggregation (real computation, stays) ---
    UNION_DF = UNION_DF.with_columns(
        pl.col("date").dt.month().alias("mois"),
        pl.col("date").dt.year().alias("annee"),
    )

    # Pivot on (mois, annee) combined so different years don't collapse together
    UNION_DF = UNION_DF.pivot(
        on=["mois", "annee"],
        index=["budget", "dept", "projet", "employé"],
        values="heures",
        aggregate_function="sum",
    )

    month_map = {
        "1": "Janvier",
        "2": "Février",
        "3": "Mars",
        "4": "Avril",
        "5": "Mai",
        "6": "Juin",
        "7": "Juillet",
        "8": "Août",
        "9": "Septembre",
        "10": "Octobre",
        "11": "Novembre",
        "12": "Décembre",
    }

    period_cols = [
        c for c in UNION_DF.columns if c not in ("budget", "dept", "projet", "employé")
    ]

    parsed_periods = []
    for col in period_cols:
        inner = col.strip("{}")  # "1,2026"
        mois_str, annee_str = inner.split(",")
        if mois_str in month_map:
            parsed_periods.append((int(annee_str), int(mois_str), col))

    parsed_periods.sort()

    # Build final display names like "Janvier 2025", "Janvier 2026"
    rename_map = {col: f"{month_map[str(mois)]}" for annee, mois, col in parsed_periods}
    ordered_display_cols = [rename_map[col] for _, _, col in parsed_periods]

    UNION_DF = UNION_DF.group_by(["budget", "dept", "employé"]).agg(
        [pl.col(col).sum() for _, _, col in parsed_periods]
    )
    UNION_DF = UNION_DF.rename(rename_map)
    month_labels = ordered_display_cols

    # Keep track of which display columns belong to which year, for GT spanners
    year_to_cols = {}
    for annee, mois, col in parsed_periods:
        year_to_cols.setdefault(annee, []).append(rename_map[col])

    # --- Filtering + dept collapsing (real logic, stays) ---
    UNION_DF = UNION_DF.filter(
        (pl.col("dept").str.starts_with("Production"))
        | (pl.col("dept").str.starts_with("Pose"))
        | (pl.col("dept").str.starts_with("Projet"))
        | (pl.col("dept").str.starts_with("Travaux"))
        | (pl.col("dept").str.starts_with("Bureau"))
    )

    UNION_DF = UNION_DF.with_columns(
        pl.when(pl.col("dept").str.starts_with("Production"))
        .then(pl.lit("Production & Méthode"))
        .otherwise(pl.col("dept"))
        .alias("dept")
    )

    # --- Final aggregation + sort ---
    final_df = (
        UNION_DF.group_by(["budget", "dept", "employé"])
        .agg([pl.col(m).sum() for m in month_labels])
        .sort(["budget", "dept", "employé"], nulls_last=True)
    )
    final_df = final_df.with_columns(
        pl.sum_horizontal(month_labels).alias("Heures Totales").round(0)
    ).sort(["budget", "Heures Totales"], descending=[False, True])

    # --- Presentation ---
    gt_table = (
        GT(final_df, rowname_col="employé", groupname_col="budget")
        .tab_header(union_json["definition"]["label"])
        .fmt_number(columns=month_labels, decimals=0)
        .summary_rows(
            fns={"TOTAL": [pl.col(m).sum() for m in month_labels]},
            fmt=lambda x: vals.fmt_number(x, decimals=0),
        )
        .grand_summary_rows(
            fns={"TOTAL GÉNÉRAL": [pl.col(m).sum() for m in month_labels]},
            fmt=lambda x: vals.fmt_number(x, decimals=0),
        )
        .tab_style(style=style.fill(color="lightblue"), locations=loc.summary())
        .tab_style(style=style.fill(color="cyan"), locations=loc.grand_summary())
        .tab_options(data_row_padding="2")
    )

    for annee, cols in year_to_cols.items():
        gt_table = gt_table.tab_spanner(label=str(annee), columns=cols)
    exec_context_list.append(
        {
            "label": union_json["definition"]["label"],
            "context_type": "union",
            "union_df": gt_table,
        }
    )


def graph_case(
    transform: dict[str, Any], full_predicates: list[bool], exec_context_list: list
):
    graph_json = json.loads(transform["content"])
    CX = graph_json["x"]
    CY = graph_json["y"]
    X_AGG = CX["aggregation"]
    Y_AGG = CY["aggregation"]

    source = None
    fig = None

    # ALTAIR
    # if type(CX) == dict:
    #     CX = alt.X(f"{CX['name']}:{ENCODING_DICT[CX['type']]}", sort="-y")

    # if type(CY) == dict:
    #     CY = alt.Y(f"{CY['name']}:{ENCODING_DICT[CY['type']]}")

    source = (
        (
            df_store.retrieve_df(graph_json["from"])["df"]
            .limit(500)
            .filter(full_predicates)
        )
        if df_store.retrieve_df(graph_json["from"])["df"].get_column(
            "create_date", default=None
        )
        is not None
        else (df_store.retrieve_df(graph_json["from"])["df"].limit(500))
    )

    match X_AGG:
        case "sum":
            source = source.group_by(graph_json["y"]["name"]).agg(
                pl.col(graph_json["x"]["name"]).sum()
            )
        case "count":
            source = source.group_by(graph_json["y"]["name"]).agg(
                pl.col(graph_json["x"]["name"]).count()
            )
        case _:
            source = source

    match Y_AGG:
        case "sum":
            source = source = source.group_by(graph_json["x"]["name"]).agg(
                pl.col(graph_json["y"]["name"]).sum()
            )
        case "count":
            source = source.group_by(graph_json["x"]["name"]).agg(
                pl.col(graph_json["y"]["name"]).count()
            )
        case _:
            source = source

    # source = source.to_pandas()
    x_label = CX["name"].replace("_", " ").capitalize()
    y_label = CY["name"].replace("_", " ").capitalize()
    labels = {
        CX["name"]: x_label,
        CY["name"]: y_label,
    }

    common_args = dict(x= CX["name"], y= CY["name"], labels= labels)
    match graph_json["graph_type"]:
        case "bar":
            fig = px.bar(source, **common_args)
        case "point":
            fig = px.scatter(source, **common_args)
        case "area":
            fig = px.area(source, **common_args)
        case _:
            fig = px.bar(source, **common_args)
    fig.update_layout(
        autosize=True,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    label = graph_json["label"]
    graph = mo.ui.plotly(figure=fig)
    # TODO make del_action works again
    # delete_button = mo.ui.button(kind="danger", label="Suppr.", on_click=del_action)
    delete_button = mo.ui.button(kind="danger", label="Suppr.")
    exec_context_list.append(
        {
            "context_type": "graph",
            "label": label,
            "graph": graph,
            "delete_button": delete_button,
        }
    )
