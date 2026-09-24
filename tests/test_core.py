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


def test_a_path_ending_with_name_is_stored_without_it():
    recs = [
        {
            "id": 1,
            "user_id": [1, "Alice"],
            "user_id.name": "Alice",
            "partner_id.country_id.name": "France",
        }
    ]
    df = Df(pl.DataFrame(recs, strict=False)).get_df()
    # `user_id` was there : the path is dropped ; the other one is renamed
    assert df.columns == ["id", "user_id", "partner_id.country_id", "user_id_"]
    assert df["partner_id.country_id"][0] == "France"


def test_every_many2one_gets_a_name_and_an_id_column():
    """Whatever the field is called : `product_uom` and `create_uid` have no `_id`
    in their name (or a different one), their id column is still `<field>_`."""
    fields = {
        name: {"type": "many2one", "rel": "x"}
        for name in ("product_uom", "create_uid", "partner_id")
    }
    recs = [
        {
            "id": 1,
            "product_uom": [1, "Units"],
            "create_uid": [2, "Bob"],
            "partner_id": [7, "Acme"],
        },
        {
            "id": 2,
            "product_uom": [3, "Dozens"],
            "create_uid": [2, "Bob"],
            "partner_id": None,
        },
    ]
    df = Df(pl.DataFrame(recs, strict=False), fields=fields).get_df()
    for name in fields:
        assert df[name].dtype == pl.String, name
        assert df[name + "_"].dtype == pl.Int64, name
    assert df["product_uom"].to_list() == ["Units", "Dozens"]
    assert df["product_uom_"].to_list() == [1, 3]
    assert df["create_uid_"].to_list() == [2, 2]
    assert "create_id_" not in df.columns


def test_df_norm_keeps_the_day():
    """Day level kpis (late, last 7 days, days to order) need exact dates."""
    recs = [{"id": 1, "date_order": "2025-01-17 23:59:00"}]
    df = Df(
        pl.DataFrame(recs, strict=False), fields={"date_order": {"type": "datetime"}}
    ).get_df()
    assert df["date_order"][0] == datetime.date(2025, 1, 17)


def test_find_dotenv_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    from kpiten_core import env

    project = tmp_path / "kpiten-core"
    (project / "src" / "kpiten_core").mkdir(parents=True)
    (project / ".env").write_text("ODOO_DB=big\n")
    elsewhere = tmp_path / "cron-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    found = env.find_dotenv(project / "src" / "kpiten_core" / "env.py")
    assert found == str(project / ".env")


def test_a_relational_path_datetime_is_a_day_like_the_other_dates():
    """`order_id.date_order` is not in the fields metadata but is a datetime :
    it must be a Date like `date_order`, or the end day of a period is cut."""
    import datetime

    from kpiten_core.dfnorm import Df

    raw = pl.DataFrame(
        {
            "id": [1],
            "date_order": [datetime.datetime(2026, 9, 18, 19, 5)],
            "order_id.date_order": [datetime.datetime(2026, 9, 18, 19, 5)],
        }
    )
    out = Df(raw, fields={"date_order": {"type": "datetime"}}).get_df()
    assert out.schema["date_order"] == pl.Date
    assert out.schema["order_id.date_order"] == pl.Date


def test_the_default_period_and_the_fiscal_year_of_kt_config():
    from kpiten_core import config, filters

    today = datetime.date(2026, 5, 20)
    span = (datetime.date(2024, 1, 1), datetime.date(2026, 5, 19))
    try:
        assert config.default_period() == "last 90 days"
        options = filters.date_options(span, today)
        assert filters.default_date_option(options, span, today) == "last 90 days"

        config.set_config({"period": {"default": ""}})  # the full range, chosen
        assert config.default_period() == ""
        assert filters.default_date_option(options, span, today) == ""

        config.set_config({"period": {"default": "year to date"}})
        options = filters.date_options(span, today)
        assert filters.default_date_option(options, span, today) == "year to date"

        # a fiscal year that starts on April 1st : 2026-04-01 -> today, and the
        # previous one to compare with is one year before
        config.set_config({"period": {"fiscal_start_month": 4}})
        assert date_filter.bounds_for_option("year to date")[0].month == 4
        bounds = (datetime.date(2026, 4, 1), today)
        assert filters.previous_bounds(bounds) == (
            datetime.date(2025, 4, 1),
            datetime.date(2025, 5, 20),
        )
        assert config.fiscal_year_start(datetime.date(2026, 2, 1)) == datetime.date(
            2025, 4, 1
        )
    finally:
        config.set_config({})


def test_date_columns_follow_the_field_type():
    """A boolean named `is_prevalidated` is no date : the type decides, not the name."""
    df = pl.DataFrame(
        {
            "is_prevalidated": [True, False],
            "invoice_date": ["2026-01-05", "2026-02-10"],
            "date_order": ["2026-01-05 10:00:00", "2026-02-10 08:30:00"],
        }
    )
    fields = {
        "is_prevalidated": {"type": "boolean"},
        "invoice_date": {"type": "date"},
        "date_order": {"type": "datetime"},
    }
    out = Df(df, fields=fields).get_df()
    assert out["is_prevalidated"].dtype == pl.Boolean
    assert out["invoice_date"].dtype == pl.Date
    assert out["date_order"].dtype == pl.Date


def test_the_amounts_of_a_foreign_order_are_in_the_company_currency():
    """108 dollars at 1.08 dollar for one euro are 100 euros : a KPI adds up euros.
    The lines reach the rate of their order ; without a rate nothing changes."""
    from kpiten_core.dfnorm import Df

    fields = {
        "amount_untaxed": {"type": "monetary"},
        "price_subtotal": {"type": "monetary"},
    }
    order = Df(
        pl.DataFrame({"amount_untaxed": [108.0, 50.0], "currency_rate": [1.08, 1.0]}),
        fields=fields,
    ).get_df()
    assert order["amount_untaxed"].to_list() == [100.0, 50.0]
    assert order["amount_untaxed_in_currency"].to_list() == [108.0, 50.0]
    line = Df(
        pl.DataFrame({"price_subtotal": [86.0], "order_id.currency_rate": [0.86]}),
        fields=fields,
    ).get_df()
    assert line["price_subtotal"].to_list() == [100.0]
    plain = Df(pl.DataFrame({"amount_untaxed": [10.0]}), fields=fields).get_df()
    assert plain.columns == ["amount_untaxed"]
