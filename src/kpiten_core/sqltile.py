"""`data` tiles written in SQL, run by the SQL engine of polars.

A definition whose first word (past the `--` comments) is SELECT or WITH is SQL ; the
others are polars snippets (`sandbox.py`). The rows the user may read, already filtered
by the panel period and dimensions, are the table `d` :

    -- the confirmed orders, by vendor
    SELECT "partner_id" AS "Vendor", SUM("amount_untaxed") AS "Untaxed"
    FROM d
    WHERE "state" IN ('purchase', 'done')
    GROUP BY "partner_id"

The values of a drill-down (`key`) and `odoo_url` are written `:name` (`:category`) : they
are bound as literals, never pasted as text. Only one SELECT (or UNION, WITH) on the
tables given is run : the SQL of polars reads any file (`read_parquet('/...')`), the store
of another user included.
"""

import re

import polars as pl
import sqlglot
from sqlglot import exp

from kpiten_spec.spec import is_sql  # noqa: F401 (the tiles ask it here)

# the functions that read a file (or a url) as a table
READERS = (exp.ReadCSV, exp.ReadParquet)
READER_NAME = re.compile(r"^(read|scan)_", re.IGNORECASE)


def check(sql: str, tables) -> exp.Expression:
    """The parsed query, when it is one SELECT (UNION, WITH) that reads only `tables`
    (and its own WITH), else ValueError."""
    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except sqlglot.errors.ParseError as err:
        raise ValueError(f"the SQL does not parse : {err}") from err
    if len(statements) != 1:
        raise ValueError("one SQL query only")
    query = statements[0]
    if not isinstance(query, exp.Query):
        raise ValueError(f"only a SELECT is allowed, not {query.key.upper()}")
    ctes = {cte.alias_or_name for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise ValueError("a table must be a name : the tile reads no file")
        if table.name not in tables and table.name not in ctes:
            known = ", ".join(sorted(tables))
            raise ValueError(f"unknown table {table.name!r} (known : {known})")
    for func in query.find_all(exp.Func):
        name = func.sql_name() if not isinstance(func, exp.Anonymous) else func.name
        if isinstance(func, READERS) or READER_NAME.match(name or ""):
            raise ValueError(f"the function {name} is not allowed")
    return query


def bind(query: exp.Expression, variables: dict) -> exp.Expression:
    """`:name` replaced by the value of `name`, as a literal."""

    def literal(node):
        if not isinstance(node, exp.Placeholder):
            return node
        if node.name not in variables:
            raise ValueError(f"unknown variable :{node.name}")
        return exp.convert(variables[node.name])

    return query.transform(literal)


def run(sql: str, tables: dict, variables: dict | None = None) -> pl.LazyFrame:
    """Run the query on `tables` (name -> frame) ; what runs is the query checked."""
    query = bind(check(sql, tables), variables or {})
    context = pl.SQLContext(
        {name: frame.lazy() for name, frame in tables.items()},
        register_globals=False,
    )
    return context.execute(query.sql())


def check_where(where: str) -> str:
    """The `where` of a card or a graph (run as `SELECT * FROM self WHERE ...`), once
    checked : it reads no other table and no file."""
    check(f"SELECT * FROM self WHERE {where}", {"self"})
    return where
