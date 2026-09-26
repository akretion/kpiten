"""Polars code step by step : each method of a chain is a step, its `#` comment above
it the words of the step.

    d_next = (
        d
        # keep the confirmed orders
        .filter(pl.col("state") == "sale")
        # the total by salesperson
        .group_by("user_id").agg(pl.col("amount_untaxed").sum().alias("total"))
    )

gives two steps, `filter` and the result (`group_by().agg()` is one step). A statement
before the last one (`orders = d.filter(...)`) gives its own steps, which the next ones
read by its name. Each step runs the code up to its method, checked by
`kpiten_core.sandbox` : `d` the table chosen, the others as `tables["sale.order.line"]`.
"""

import ast
import io
import tokenize

from .steps import RESULT, Step

OUT = "step_out"  # the variable of the code of a step

KINDS = {
    "filter": "filter",
    "drop_nulls": "filter",
    "with_columns": "compute",
    "with_row_index": "compute",
    "rename": "compute",
    "fill_null": "compute",
    "fill_nan": "compute",
    "cast": "compute",
    "explode": "compute",
    "unnest": "compute",
    "select": "select",
    "drop": "select",
    "join": "join",
    "group_by": "group",
    "group_by_dynamic": "group",
    "agg": "group",
    "pivot": "group",
    "unpivot": "group",
    "melt": "group",
    "unique": "distinct",
    "sort": "sort",
    "head": "limit",
    "limit": "limit",
    "tail": "limit",
    "slice": "limit",
    "vstack": "union",
}
GROUPING = ("group_by", "group_by_dynamic")


def _comments(code: str) -> dict[int, str]:
    """The `#` comments of the code, by line."""
    found = {}
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type == tokenize.COMMENT:
            found[token.start[0]] = token.string.lstrip("#").strip()
    return found


def _chain(node: ast.expr) -> tuple[ast.expr, list[ast.Call]]:
    """(base, calls) : `d.filter(...).sort(...)` gives `d` and the two calls, in
    order ; a call is the whole chain up to its method."""
    calls = []
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        calls.append(node)
        node = node.func.value
    return node, calls[::-1]


def _table(node: ast.expr) -> str | None:
    """The table a base names : `d`, `tables["sale.order.line"]`, or a variable."""
    if isinstance(node, ast.Name):
        return node.id
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "tables"
        and isinstance(node.slice, ast.Constant)
    ):
        return node.slice.value
    return None


def _words(code: str, comments: dict, call: ast.Call) -> str:
    """The comment above the method of a call (and on its line)."""
    line = call.func.end_lineno  # the line of `.method`
    words = [comments[line]] if line in comments else []
    above = []
    line -= 1
    while line in comments and not code.splitlines()[line - 1].strip().startswith("."):
        above.insert(0, comments[line])
        line -= 1
    return " ".join(above + words)


def _columns(call: ast.Call) -> list[str]:
    """The columns a call names : `pl.col("x")`, and the strings of `by`, `on`..."""
    names = []
    for node in ast.walk(call):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in names and "%" not in node.value:
                names.append(node.value)
    return names


def split_polars(code: str) -> list[Step]:
    """The steps of polars code : one per method of the chain of each statement (its
    `group_by().agg()` as one) ; the last one is the result."""
    tree = ast.parse(code)
    comments = _comments(code)
    setup, steps, last_of = [], [], {}
    for statement in tree.body:
        source = ast.get_source_segment(code, statement)
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            setup.append(source)
            continue
        base, calls = _chain(statement.value)
        table = _table(base)
        previous = last_of.get(table)  # a variable of a statement before
        i = 0
        while i < len(calls):
            first = call = calls[i]
            methods = [call.func.attr]
            if methods[0] in GROUPING and i + 1 < len(calls):
                i += 1  # group_by(...).agg(...) : one step
                call = calls[i]
                methods.append(call.func.attr)
            i += 1
            chain = ast.get_source_segment(code, call)
            # what the step adds : the chain past what the steps before it wrote
            shown = chain[len(ast.get_source_segment(code, first.func.value)) :]
            name = "_".join(methods)
            while name in {s.name for s in steps}:
                name += "_"
            step_code = "\n".join([*setup, f"{OUT} = (\n{chain}\n)"])
            kinds = [KINDS.get(m, "compute") for m in methods]
            if "over(" in shown:
                kinds.append("window")
            step = Step(
                name,
                step_code,
                " ".join(  # group_by(...).agg(...) : the words above either
                    dict.fromkeys(
                        w
                        for w in (_words(code, comments, c) for c in (first, call))
                        if w
                    )
                ),
                list(dict.fromkeys(kinds)),
                [table] if previous is None else [],
                _columns(call),
                after=previous,
                clause=True,
            )
            shown = "\n".join(
                line.strip()
                for line in shown.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
            step.language, step.shown = "polars", shown.lstrip(".")
            if "join" in kinds and call.args:
                step.other = _table(_chain(call.args[0])[0])
                step.join_on = ", ".join(
                    ast.get_source_segment(code, k.value)
                    for k in call.keywords
                    if k.arg in ("on", "left_on", "right_on")
                )
                step.join_how = next(
                    (
                        k.value.value
                        for k in call.keywords
                        if k.arg == "how" and isinstance(k.value, ast.Constant)
                    ),
                    "inner",
                )
            steps.append(step)
            previous = step.name
        last_of[statement.targets[0].id] = previous
        setup.append(source)
    if steps:
        steps[-1].name = RESULT
    return steps
