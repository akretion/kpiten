import datetime

import polars as pl

from kpiten_core import date_filter
from kpiten_core.dfnorm import Df
from kpiten_core import month

VALUES_DATES = [
    datetime.date(2025, 1, 15),
    datetime.date(2025, 2, 15),
    datetime.date(2025, 3, 15),
]


def test_bounds_last_year():
    b = date_filter.last_year_bounds(datetime.date(2025, 6, 1))
    assert b["LY_first_day"] == datetime.date(2024, 1, 1)
    assert b["LY_last_day"] == datetime.date(2024, 12, 31)


def test_predicate_on_column():
    predicates = date_filter.process_dt_predicate(
        (datetime.date(2025, 2, 1), datetime.date(2025, 12, 31)), "date_order"
    )
    df = pl.DataFrame({"date_order": VALUES_DATES})
    res = df.filter(predicates)
    assert len(res) == 2


def test_monthly():
    df = pl.DataFrame({"d": VALUES_DATES})
    res = month.apply_monthly(df, "d")
    assert res["d"].to_list() == [datetime.date(2025, m, 1) for m in (1, 2, 3)]
    assert month.is_date(df, "d")
    assert not month.is_date(df, "unknown")


def test_df_norm_many2one_split():
    recs = [
        {"id": 1, "user_id": [1, "Alice"], "date_order": "2025-01-05 10:00:00"},
        {"id": 2, "user_id": [2, "Bob"], "date_order": "2025-02-05 10:00:00"},
    ]
    df = Df(
        pl.DataFrame(recs, strict=False), fields={"date_order": {"type": "datetime"}}
    ).get_df()
    assert "user_id_" in df.columns
    assert df["user_id"][0] == "Alice"
    assert df["user_id_"][0] == 1
    assert df["date_order"].dtype == pl.Date
