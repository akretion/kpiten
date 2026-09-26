"""A derived table step by step : its SQL cut into steps, one per CTE, each run on the
tables of the user and measured.

    WITH
    -- Step 1 : the confirmed orders
    confirmed AS (SELECT * FROM d WHERE state IN ('sale', 'done')),
    -- Step 2 : the total by salesperson
    by_user AS (SELECT user_id, SUM(amount_untaxed) AS total FROM confirmed GROUP BY 1)
    SELECT * FROM by_user ORDER BY total DESC LIMIT 10

gives three steps : `confirmed`, `by_user` and the result. The numbers (rows, columns,
groups) come from polars, never from the words of the comments. Every query goes through
`sqltile.run` : one SELECT on the tables given, no file read.
"""

import re
from dataclasses import dataclass, field

import polars as pl
import sqlglot
from sqlglot import exp

from kpiten_core import sqltile

RESULT = "result"  # the name of the last step, the query past its WITH
SAMPLE_ROWS = 10
TOP_GROUPS = 10

# the kinds of a step, the first one found is its main kind
KINDS = (
    "union",
    "join",
    "group",
    "distinct",
    "window",
    "filter",
    "compute",
    "sort",
    "limit",
    "select",
)
# `-- Step 2 : ...`, `-- Étape 2 : ...` : the number is the place of the step
NUMBERING = re.compile(r"^\s*(step|étape|etape)\s*\d+\s*[:.)-]?\s*", re.IGNORECASE)


@dataclass
class Step:
    name: str  # the CTE, or RESULT
    sql: str  # the query of the step alone : the steps before it are its tables
    comment: str = ""  # what the step does, in words (the comment above the CTE)
    kinds: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # the tables read, FROM first
    used: list[str] = field(default_factory=list)  # the columns its SQL names
    after: str | None = None  # a clause : the step it follows (its rows in)
    clause: bool = False  # a clause of a query without CTE : no table of its own

    @property
    def kind(self) -> str:
        return self.kinds[0] if self.kinds else "select"


@dataclass
class StepResult:
    step: Step
    rows_in: int | None  # the rows of its first table, None without one
    rows_out: int
    columns_in: list[str]
    columns: list[str]
    sample: pl.DataFrame
    detail: dict = field(default_factory=dict)  # by kind, when the detail is asked

    @property
    def columns_added(self) -> list[str]:
        return [c for c in self.columns if c not in self.columns_in]

    @property
    def columns_removed(self) -> list[str]:
        return [c for c in self.columns_in if c not in self.columns]


VALID_COLUMNS = re.compile(r";?\s*valid columns: \[[^\]]*\]?")


def short_error(err, limit: int = 800, columns: bool = True) -> str:
    """The message of an error (or its text) without the plan polars adds (`Resolved
    plan until failure`, dozens of lines) : what is needed to fix the query. Without
    `columns`, for the user : no list of every column (its `Did you mean` stays)."""
    text = str(err).split("\n\nResolved plan")[0].strip()
    # the list of the columns is cut, not what follows it (`Did you mean ...`)
    cut = lambda m: (
        m.group(0) if len(m.group(0)) <= limit else m.group(0)[:limit] + " ...]"
    )
    text = VALID_COLUMNS.sub(cut if columns else "", text)
    return text if len(text) <= 2 * limit else text[: 2 * limit] + " ..."


def _parse(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except sqlglot.errors.ParseError as err:
        raise ValueError(f"the SQL does not parse : {err}") from err
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("one SELECT only")
    return statements[0]


def _comment(*nodes) -> str:
    """The comment written above a CTE (or the query), without its `Step n :`."""
    for node in nodes:
        lines = [c.strip() for c in (node.comments or []) if c.strip()]
        if lines:
            return NUMBERING.sub("", " ".join(lines))
    return ""


def _plain(node: exp.Expression) -> str:
    """The SQL of a node, without its comments."""
    node = node.copy()
    for n in node.walk():
        n.comments = None
    return node.sql()


def _is_aggregate(node: exp.Expression) -> bool:
    return any(
        isinstance(n, exp.AggFunc) and not n.find_ancestor(exp.Window)
        for n in node.walk()
    )


def _kinds(node: exp.Expression) -> list[str]:
    if isinstance(node, exp.SetOperation):
        return ["union"]
    if not isinstance(node, exp.Select):
        return ["select"]
    found = set()
    if node.args.get("joins"):
        found.add("join")
    if node.args.get("group") or any(_is_aggregate(e) for e in node.expressions):
        found.add("group")
    if node.args.get("distinct"):
        found.add("distinct")
    if any(node.find_all(exp.Window)):
        found.add("window")
    if node.args.get("where") or node.args.get("having"):
        found.add("filter")
    for expression in node.expressions:
        value = expression.unalias()
        if isinstance(value, (exp.Star, exp.Column)) or _is_aggregate(value):
            continue
        if not value.find(exp.Window):
            found.add("compute")
    if node.args.get("order"):
        found.add("sort")
    if node.args.get("limit"):
        found.add("limit")
    return [k for k in KINDS if k in found] or ["select"]


def _sources(node: exp.Expression) -> list[str]:
    """The tables a SELECT reads by its FROM and its JOIN (not in its subqueries)."""
    if isinstance(node, exp.SetOperation):
        return _sources(node.left) + _sources(node.right)
    if not isinstance(node, exp.Select):
        return []
    tables = []
    from_ = node.args.get("from_")
    for part in [from_, *(node.args.get("joins") or [])]:
        if part is not None and isinstance(part.this, exp.Table):
            tables.append(part.this.name)
    return tables


def _used(node: exp.Expression) -> list[str]:
    names = []
    for column in node.find_all(exp.Column):
        if column.name and column.name not in names:
            names.append(column.name)
    return names


def _step(name: str, node: exp.Expression, comment: str) -> Step:
    return Step(name, _plain(node), comment, _kinds(node), _sources(node), _used(node))


def _clauses(node: exp.Select, comment: str) -> list[Step]:
    """A SELECT without CTE, cut in the order the database runs its clauses : FROM and
    JOIN, WHERE, the SELECT (GROUP BY, HAVING, DISTINCT, windows), ORDER BY, LIMIT.
    Each step is the query up to its clause ; the last one is the whole query."""
    tables = _sources(node)
    names = " and ".join(tables)
    parts = [
        (
            "from",
            _base(node),
            f"The rows of {names}" + (", joined" if len(tables) > 1 else ""),
        )
    ]
    if node.args.get("where"):
        upto = _base(node)
        upto.set("where", node.args["where"].copy())
        parts.append(("where", upto, "Keep the rows that meet the conditions"))
    upto = node.copy()
    upto.set("order", None)
    upto.set("limit", None)
    kinds = _kinds(upto)
    words = (
        "One row per group"
        if "group" in kinds
        else "Each row once" if "distinct" in kinds else "The columns of the result"
    )
    keeps_all = all(isinstance(e, exp.Star) for e in upto.expressions)
    if not (keeps_all and set(kinds) <= {"join", "filter", "select"}):
        parts.append(("select", upto, words))  # it does something : a step
    if node.args.get("order"):
        upto = upto.copy()
        upto.set("order", node.args["order"].copy())
        parts.append(("order", upto, "In order"))
    if node.args.get("limit"):
        parts.append(("limit", node.copy(), "The first rows only"))
    steps, previous = [], None
    for i, (name, query, words) in enumerate(parts):
        last = i == len(parts) - 1
        own = {"from": ["join"] if len(tables) > 1 else ["select"], "where": ["filter"]}
        kinds = own.get(name) or {"order": ["sort"], "limit": ["limit"]}.get(name)
        if kinds is None:  # the select : what it does besides the clauses before
            kinds = [k for k in _kinds(query) if k not in ("join", "filter")]
            if query.args.get("having"):
                kinds.append("filter")
        step = _step(
            RESULT if last else name, query, (comment if last else "") or words
        )
        step.kinds, step.after, step.clause = kinds or ["select"], previous, True
        steps.append(step)
        previous = step.name
    return steps


def split(sql: str) -> list[Step]:
    """The steps of a query : one per CTE of its WITH, then the query itself. A query
    without CTE is cut by its clauses (`_clauses`), when it has more than one."""
    query = _parse(sql)
    steps = []
    with_ = query.args.get("with_")
    if with_ is not None:
        for cte in with_.expressions:
            steps.append(_step(cte.alias, cte.this, _comment(cte.args["alias"], cte)))
        query = query.copy()
        query.set("with_", None)
    elif isinstance(query, exp.Select) and query.args.get("from_") is not None:
        steps = _clauses(query, _comment(query))
        if len(steps) > 1:
            return steps
        steps = []
    steps.append(_step(RESULT, query, _comment(query)))
    return steps


def reads(sql: str) -> list[str]:
    """The tables a query reads (its own CTE left out), in their order."""
    query = _parse(sql)
    ctes = {cte.alias_or_name for cte in query.find_all(exp.CTE)}
    names = []
    for table in query.find_all(exp.Table):
        if table.name not in ctes and table.name not in names:
            names.append(table.name)
    return names


def polars_code(sql: str, source: str, db: str = "") -> str:
    """The query as python : polars runs it lazily on the store of the user (what
    to copy in a notebook or a script of one's own)."""
    frames = ", ".join(
        f'"{name}": store["{source if name == "d" else name}"]' for name in reads(sql)
    )
    return f"""import polars as pl
from kpiten_core.backend import Backend
from kpiten_core.loaders import user_store

# the rows and the columns user_id may read in Odoo
store = user_store(Backend.create(db="{db}"), user_id)
query = \"\"\"
{sql.strip()}
\"\"\"
result = pl.SQLContext({{{frames}}}).execute(query)  # lazy : .collect() runs it
"""


def _count(frame: pl.LazyFrame) -> int:
    return frame.select(pl.len()).collect().item()


def _base(node: exp.Select) -> exp.Select:
    """The rows a SELECT starts from : its FROM and JOIN, without anything else."""
    base = exp.select("*")
    base.set("from_", node.args["from_"].copy())
    base.set("joins", [j.copy() for j in node.args.get("joins") or []] or None)
    return base


def _filter_detail(node: exp.Select, tables: dict) -> dict:
    """The rows each condition of the WHERE removes alone (its AND terms)."""
    where = node.args.get("where")
    base = _base(node)
    rows = _count(sqltile.run(base.sql(), tables))
    terms = []
    for term in (
        where.this.flatten() if isinstance(where.this, exp.And) else [where.this]
    ):
        kept = _count(sqltile.run(base.copy().where(term.copy()).sql(), tables))
        terms.append({"condition": _plain(term), "removed": rows - kept})
    return {"rows": rows, "terms": terms}


def _join_detail(node: exp.Select, tables: dict) -> list[dict]:
    """For each JOIN : the rows before and after it ; more rows after an inner or a left
    join means a row found several matches (an amount counted twice)."""
    joins = node.args.get("joins") or []
    base = _base(node)
    before = _count(
        sqltile.run(exp.select("*").from_(base.args["from_"]).sql(), tables)
    )
    found = []
    for i, join in enumerate(joins):
        upto = base.copy()
        upto.set("joins", [j.copy() for j in joins[: i + 1]])
        after = _count(sqltile.run(upto.sql(), tables))
        table = (
            join.this.name if isinstance(join.this, exp.Table) else _plain(join.this)
        )
        other = tables.get(table)
        found.append(
            {
                "table": table,
                "on": _plain(join.args["on"]) if join.args.get("on") else "",
                "side": " ".join(
                    filter(None, [join.args.get("side"), join.args.get("kind")])
                ).upper()
                or "INNER",
                "rows_before": before,
                "rows_after": after,
                "rows_other": _count(other) if other is not None else None,
            }
        )
        before = after
    return found


def _group_keys(node: exp.Select) -> list[tuple[str, exp.Expression]]:
    """(name, expression) of each key of the GROUP BY : `GROUP BY 1` and `GROUP BY
    category` (an alias of the SELECT) are replaced by what they stand for."""
    aliases = {e.alias: e.unalias() for e in node.expressions if e.alias}
    keys = []
    for key in node.args["group"].expressions:
        if isinstance(key, exp.Literal) and key.is_int:  # GROUP BY 1, 2
            selected = node.expressions[int(key.this) - 1]
            keys.append((selected.alias_or_name, selected.unalias().copy()))
        elif isinstance(key, exp.Column) and not key.table and key.name in aliases:
            keys.append((key.name, aliases[key.name].copy()))
        else:
            keys.append((key.alias_or_name, key.copy()))
    return keys


def _group_detail(node: exp.Select, tables: dict) -> dict:
    """The number of rows in each group, the largest first."""
    keys = _group_keys(node)
    sizes = _base(node)
    sizes.set(
        "expressions",
        [exp.alias_(key, name, quoted=True) for name, key in keys]
        + [exp.alias_(exp.Count(this=exp.Star()), "rows")],
    )
    if node.args.get("where"):
        sizes.set("where", node.args["where"].copy())
    sizes.set("group", exp.Group(expressions=[key.copy() for _, key in keys]))
    frame = sqltile.run(sizes.sql(), tables).collect()
    frame = frame.sort("rows", descending=True)
    return {
        "groups": frame.height,
        "largest": frame.head(TOP_GROUPS),
        "min": frame["rows"].min() if frame.height else 0,
        "max": frame["rows"].max() if frame.height else 0,
    }


def _detail(step: Step, tables: dict) -> dict:
    """The detail of a step, by kind ; a part that fails is left out, with its error."""
    node = _parse(step.sql)
    if not isinstance(node, exp.Select) or node.args.get("from_") is None:
        return {}
    detail, parts = {}, []
    # only what the step does itself : a clause does not repeat those before it
    if node.args.get("where") and "filter" in step.kinds:
        parts.append(("filter", _filter_detail))
    if node.args.get("joins") and "join" in step.kinds:
        parts.append(("join", _join_detail))
    if node.args.get("group") and "group" in step.kinds:
        parts.append(("group", _group_detail))
    for kind, compute in parts:
        try:
            detail[kind] = compute(node, tables)
        except Exception as err:
            detail.setdefault("errors", []).append(f"{kind} : {err}")
    return detail


def trace(
    steps: list[Step],
    tables: dict,
    detail: bool = False,
    sample_rows: int = SAMPLE_ROWS,
) -> list[StepResult]:
    """Run the steps one after the other on `tables` (name -> frame : the store of the
    user) ; each step reads the tables and the steps before it. The counts are on every
    row, the sample only is cut."""
    frames = {name: frame.lazy() for name, frame in tables.items()}
    results, outputs = [], {}
    for step in steps:
        frame = sqltile.run(step.sql, frames)
        if step.after:  # a clause : its rows in are the rows of the clause before
            first = outputs[step.after]
        else:
            first = frames.get(step.sources[0]) if step.sources else None
        result = StepResult(
            step,
            rows_in=_count(first) if first is not None else None,
            rows_out=_count(frame),
            columns_in=first.collect_schema().names() if first is not None else [],
            columns=frame.collect_schema().names(),
            sample=frame.head(sample_rows).collect(),
        )
        if detail:
            result.detail = _detail(step, frames)
        results.append(result)
        outputs[step.name] = frame
        if step.name != RESULT and not step.clause:
            frames[step.name] = frame  # a CTE : the steps after it read it by its name
    return results
