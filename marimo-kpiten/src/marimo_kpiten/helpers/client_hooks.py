"""Client-specific KPI logic, kept out of the generic lib.

Register hooks here with the decorators from marimo_kpiten.helpers.hooks.
"""

import polars as pl
from great_tables import GT, vals, style, loc

from marimo_kpiten.helpers.hooks import register_df, register_union_old
from marimo_kpiten.services.df_storage import DFStorage as df_store

MONTHS_FR = {
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


@register_df("account.analytic.line")
def account_analytic_line(df):
    """Prep the analytic lines df (invoiced timesheets by month)."""
    df = (
        df.filter(
            pl.col("category").eq("invoice"),
            pl.col("product_id_").is_not_null(),
            pl.col("plan_id.name").str.contains("Projet"),
            pl.col("move_line_id.display_type").eq("product"),
            pl.col("date").dt.year().eq(2026),
        )
        .with_columns(
            pl.col("date").dt.month().alias("mois"),
            pl.col("date").dt.year().alias("annee"),
        )
        .group_by(["move_id.name", "annee", "mois"])
        .agg(pl.col("amount").sum(), pl.col("price_subtotal").sum())
        .sort(by=["move_id.name"], descending=True)
    )
    return df.with_columns(
        pl.col("mois").cast(pl.Utf8).replace(MONTHS_FR).alias("mois")
    )


@register_union_old("account.analytic.line")
def timesheets_union_old(union_json, full_predicates, label):
    """Union of analytic lines and workcenter productivity, pivoted by month."""
    base_model_df = (
        df_store.retrieve_df(union_json["definition"]["model"]["name"])["df"]
        .filter(
            pl.col("department_id").is_not_null(),
            pl.col("budget_type").is_not_null(),
        )
        .filter(full_predicates)
    )
    union_model_df = (
        df_store.retrieve_df(union_json["definition"]["union_model"]["name"])["df"]
        .filter(full_predicates)
        .with_columns(pl.lit("production").alias("description"))
    )

    bmdf_columns = union_json["definition"]["model"]["columns"]
    umdf_columns = union_json["definition"]["union_model"]["columns"]
    base_model_df = base_model_df.select(bmdf_columns.keys()).rename(bmdf_columns)
    union_model_df = union_model_df.select(umdf_columns.keys()).rename(umdf_columns)

    union_df = pl.concat([base_model_df, union_model_df], how="vertical_relaxed")

    union_df = union_df.with_columns(
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

    union_df = union_df.with_columns(
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

    union_df = union_df.with_columns(
        pl.when(pl.col("budget") == "production")
        .then(pl.lit("FAB"))
        .when(pl.col("budget") == "installation")
        .then(pl.lit("POSE"))
        .when(pl.col("budget") == "service")
        .then(pl.lit("BE"))
        .otherwise(pl.col("budget"))
        .alias("budget")
    )

    union_df = union_df.with_columns(
        pl.col("date").dt.month().alias("mois"),
        pl.col("date").dt.year().alias("annee"),
    )

    union_df = union_df.pivot(
        on=["mois", "annee"],
        index=["budget", "dept", "projet", "employé"],
        values="heures",
        aggregate_function="sum",
    )

    period_cols = [
        c for c in union_df.columns if c not in ("budget", "dept", "projet", "employé")
    ]

    parsed_periods = []
    for col in period_cols:
        inner = col.strip("{}")  # "1,2026"
        mois_str, annee_str = inner.split(",")
        if mois_str in MONTHS_FR:
            parsed_periods.append((int(annee_str), int(mois_str), col))
    parsed_periods.sort()

    rename_map = {col: MONTHS_FR[str(mois)] for annee, mois, col in parsed_periods}
    month_labels = [rename_map[col] for _, _, col in parsed_periods]

    union_df = (
        union_df.group_by(["budget", "dept", "employé"])
        .agg([pl.col(col).sum() for _, _, col in parsed_periods])
        .rename(rename_map)
    )

    year_to_cols = {}
    for annee, mois, col in parsed_periods:
        year_to_cols.setdefault(annee, []).append(rename_map[col])

    union_df = union_df.filter(
        (pl.col("dept").str.starts_with("Production"))
        | (pl.col("dept").str.starts_with("Pose"))
        | (pl.col("dept").str.starts_with("Projet"))
        | (pl.col("dept").str.starts_with("Travaux"))
        | (pl.col("dept").str.starts_with("Bureau"))
    ).with_columns(
        pl.when(pl.col("dept").str.starts_with("Production"))
        .then(pl.lit("Production & Méthode"))
        .otherwise(pl.col("dept"))
        .alias("dept")
    )

    final_df = (
        union_df.group_by(["budget", "dept", "employé"])
        .agg([pl.col(m).sum() for m in month_labels])
        .sort(["budget", "dept", "employé"], nulls_last=True)
    )
    final_df = final_df.with_columns(
        pl.sum_horizontal(month_labels).alias("Heures Totales").round(0)
    ).sort(["budget", "Heures Totales"], descending=[False, True])

    gt_table = (
        GT(final_df, rowname_col="employé", groupname_col="budget")
        .tab_header(label)
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
    return gt_table
