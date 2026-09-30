"""The derived tables (`kt.derived.table`) computed on the store of a user.

A derived table is a SQL query on the tables of the store (the one it names `source` is
read as `d`, the others by their name in double quotes) and on the other derived tables ;
or polars code (`language` "polars") : a chain on `d` that ends in `d_next`, the other
tables read as `tables["sale.order.line"]`, run by `kpiten_core.sandbox`.
It is computed lazily on the `user_store` of the user who reads it : a table shared by
a KpiTen manager shows every user their own rows only.

    tables, errors = derived.resolve(store, backend.get_derived_tables(user_id))

The tiles and the fronts read them as tables of the store, by their name.
"""

import ast

import sqlglot
from sqlglot import exp

from kpiten_core import sandbox, sqltile


def _reads_polars(code: str) -> set[str]:
    """The tables polars code reads : its `tables["name"]`."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "tables"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }


def run_polars(code: str, tables: dict, d=None):
    """The `d_next` of polars code, checked by the sandbox : `d` the table chosen, the
    others in `tables` (a LazyFrame when the code keeps it lazy)."""
    return sandbox.run(code, d, "d", "d_next", variables={"tables": tables})


def _reads(sql: str, language: str = "sql") -> set[str]:
    """The tables a query reads, its own CTE left out."""
    if language == "polars":
        return _reads_polars(sql)
    try:
        query = sqlglot.parse_one(sql)
    except sqlglot.errors.ParseError:
        return set()
    ctes = {cte.alias_or_name for cte in query.find_all(exp.CTE)}
    return {t.name for t in query.find_all(exp.Table)} - ctes


def _chosen(definitions: list[dict]) -> dict[str, dict]:
    """One definition per name : the user's own before a shared one."""
    chosen = {}
    for definition in sorted(definitions, key=lambda d: not d.get("mine")):
        chosen.setdefault(definition["name"], definition)
    return chosen


def resolve(store: dict, definitions: list[dict]) -> tuple[dict, dict]:
    """(tables, errors) : the derived tables as lazy frames (name -> frame), each one
    computed after those it reads ; `errors` : name -> why a table is left out (a
    cycle, an unknown table, a query that does not run)."""
    chosen = _chosen(definitions)
    reads = {
        name: _reads(d["sql"], d.get("language") or "sql") & set(chosen)
        for name, d in chosen.items()
    }
    tables, errors = {}, {}

    def build(name: str, path: tuple = ()):
        if name in tables or name in errors:
            return
        if name in path:
            errors[name] = "a cycle : " + " → ".join((*path, name))
            return
        for other in sorted(reads[name] - {name}):
            build(other, (*path, name))
            if other in errors:  # a cycle names its first table : kept
                errors.setdefault(name, f"it reads {other}, left out")
                return
        definition = chosen[name]
        frames = store | tables
        source = definition.get("source")
        if source:
            if source not in store:
                errors[name] = f"its table {source} is not in your scope"
                return
            frames["d"] = store[source]
        try:
            if definition.get("language") == "polars":
                d = frames.pop("d", None)
                tables[name] = run_polars(definition["sql"], frames, d).lazy()
            else:
                tables[name] = sqltile.run(definition["sql"], frames)
        except Exception as err:
            errors[name] = str(err)

    for name in chosen:
        build(name)
    return tables, errors
