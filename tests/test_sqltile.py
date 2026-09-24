import polars as pl
import pytest

from kpiten_core import sqltile, tiles

ORDERS = pl.DataFrame(
    {
        "partner_id": ["Metalis", "Léman", "Metalis", "Kerval"],
        "state": ["purchase", "purchase", "done", "draft"],
        "amount_untaxed": [100.0, 40.0, 60.0, 999.0],
    }
)
STORE = {"purchase.order": ORDERS}

SQL = """-- the confirmed orders, by vendor
SELECT "partner_id" AS "Vendor", SUM("amount_untaxed") AS "Untaxed"
FROM d
WHERE "state" IN ('purchase', 'done')
GROUP BY "partner_id"
ORDER BY "Untaxed" DESC"""

POLARS = """d_next = d
d_next = d_next.filter(pl.col("state").is_in(["purchase", "done"]))
d_next = d_next.group_by("partner_id").agg(pl.col("amount_untaxed").sum().alias("Untaxed"))
d_next = d_next.sort("Untaxed", descending=True).rename({"partner_id": "Vendor"})"""


def run(content, extra=None):
    return tiles.dataframe_case(content, "purchase.order", STORE, [], extra).collect()


def test_a_sql_tile_gives_what_its_polars_twin_gives():
    assert sqltile.is_sql(SQL) and not sqltile.is_sql(POLARS)
    assert run(SQL).to_dicts() == run(POLARS).to_dicts()
    assert run(SQL)["Vendor"].to_list() == ["Metalis", "Léman"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_parquet('/tmp/another_user.parquet')",
        "SELECT * FROM d WHERE state IN (SELECT state FROM read_csv('/etc/passwd'))",
        "SELECT * FROM stock_move",
        "SELECT * FROM d; SELECT * FROM d",
    ],
)
def test_a_file_an_unknown_table_or_a_second_query_is_refused(sql):
    with pytest.raises(ValueError):
        sqltile.run(sql, {"d": ORDERS})


def test_a_polars_snippet_runs_sql_checked_like_a_sql_tile():
    mixed = """d_next = d
d_next = sql('SELECT "partner_id", "amount_untaxed" FROM d WHERE "state" <> \\'draft\\'')
d_next = sql('SELECT "partner_id" AS "Vendor", SUM("amount_untaxed") AS "Untaxed" '
             'FROM t GROUP BY "partner_id"', t=d_next)
d_next = d_next.sort("Untaxed", descending=True)"""
    assert run(mixed).to_dicts() == run(POLARS).to_dicts()
    with pytest.raises(ValueError, match="reads no file"):
        run("d_next = d\nd_next = sql(\"SELECT * FROM read_parquet('/tmp/x')\")")


def test_only_a_select_runs():
    with pytest.raises(ValueError, match="only a SELECT"):
        sqltile.check("DELETE FROM d", {"d"})


def test_a_variable_is_bound_as_a_literal():
    key = {"vendor": "L'éman ; DROP"}
    df = sqltile.run(
        'SELECT COUNT(*) AS n FROM d WHERE "partner_id" = :vendor', {"d": ORDERS}, key
    ).collect()
    assert df["n"][0] == 0
    with pytest.raises(ValueError, match="unknown variable"):
        sqltile.run("SELECT * FROM d WHERE state = :other", {"d": ORDERS}, key)


def test_a_drill_down_in_sql_reads_its_key():
    df = run(
        'SELECT "amount_untaxed" FROM d WHERE "partner_id" = :partner_id',
        {"key": {"partner_id": "Metalis"}, "tables": {}},
    )
    assert sorted(df["amount_untaxed"]) == [60.0, 100.0]


def test_the_where_of_a_card_reads_no_file():
    assert sqltile.check_where("state = 'done'") == "state = 'done'"
    with pytest.raises(ValueError):
        sqltile.check_where("1 = 1 UNION SELECT * FROM read_parquet('/x.parquet')")
