"""A new KPI from a tile and the filters it is seen with.

The dimensions chosen in the panel and the filters the AI made (on the tile, on the
panel) are written in the `where` of a copy of the tile, which can then go on any
panel. The period is not written : the tile follows the period of the panel it is put
on. A card, a graph and a pivot read one table (the one of their dataset, or `from`) :
the conditions are on its columns. A union reads two : its `where` is on the rows of the
union, the conditions on the table of its dataset are renamed by its `mapping`.
"""

import sqlglot
from sqlglot import exp

from kpiten_core import serial, sqltile

WHERE_KINDS = ("card", "graph", "pivot", "union")


def tile_table(line: dict) -> str:
    """The table the rows of a tile come from : `from`, else the one of its dataset."""
    if line.get("kind") in ("card", "graph", "pivot"):
        try:
            return serial.loads(line.get("content") or "").get("from") or line["model"]
        except Exception:
            return line["model"]
    return line["model"]


def dimension_conditions(
    filter_config: dict, dim_values: dict[str, list], columns
) -> list[str]:
    """The dimensions chosen in the panel, as SQL : `"user_id" IN ('Marie')`, for the
    columns the table has."""
    conditions = []
    for dim in filter_config.get("dimensions", []):
        column, selected = dim["name"], dim_values.get(dim["name"])
        if selected and column in columns:
            values = [exp.convert(value) for value in selected]
            conditions.append(exp.column(column, quoted=True).isin(*values).sql())
    return conditions


def _renamed(where: str, names: dict[str, str]) -> str:
    """The condition with its columns renamed (those of a table -> those of a union) ;
    ValueError for a column the union does not have."""

    def rename(node):
        if not isinstance(node, exp.Column):
            return node
        if node.name not in names:
            raise ValueError(f"the union has no column for {node.name!r}")
        return exp.column(names[node.name], quoted=True)

    return sqlglot.parse_one(where).transform(rename).sql()


def new_definition(line: dict, conditions: list[str]) -> str:
    """The definition of the tile with `conditions` added to its `where` (AND)."""
    kind = line.get("kind")
    if kind not in WHERE_KINDS:
        raise ValueError(f"a {kind} tile has no `where`")
    definition = serial.loads(line.get("content") or "")
    if kind == "union":
        mapping = definition["mapping"]
        conditions = [_renamed(c, mapping.get(line["model"], {})) for c in conditions]
    wanted = [definition["where"]] if definition.get("where") else []
    wanted += [c for c in conditions if c]
    if wanted:
        where = " AND ".join(f"({c})" if len(wanted) > 1 else c for c in wanted)
        definition["where"] = sqltile.check_where(where)
    return serial.dumps(definition)
