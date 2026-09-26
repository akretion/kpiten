"""The steps of a derived table drawn in html : the same page for marimo and Shiny.

Each step is a `<details>` : its words, its rows before and after (with a bar, the size of
the table along the steps), the columns it adds or removes ; open, a sample of its rows.
The detail (for a KpiTen manager) adds the SQL of the step and what `trace` measured :
the rows each condition removes, the rows a join adds, the size of the groups.
"""

import html

import polars as pl

from .steps import RESULT, StepResult

SAMPLE_COLUMNS = 8

ICONS = {
    "union": ("🧩", "Union : the rows of several tables, one after the other"),
    "join": ("🔗", "Join : the columns of another table, matched row by row"),
    "group": ("📦", "Group : one row per group, the values added up"),
    "distinct": ("🧹", "Distinct : the repeated rows kept once"),
    "window": ("🪟", "Window : a value computed on the neighbouring rows"),
    "filter": ("🔍", "Filter : only the rows that meet the conditions"),
    "compute": ("➕", "Computed column : a new column, from the others"),
    "sort": ("↕️", "Sort : the rows in order"),
    "limit": ("✂️", "Limit : the first rows only"),
    "select": ("📋", "Select : some columns of the table"),
}

STYLE = """
<style>
.kt-steps { font-size: 0.92rem; display: flex; flex-direction: column; gap: 6px; }
.kt-step { border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
  border-radius: 8px; padding: 2px 10px; }
.kt-step[open] { padding-bottom: 10px; }
.kt-step summary { display: flex; align-items: center; gap: 10px; cursor: pointer;
  padding: 6px 0; list-style: none; }
.kt-step summary::-webkit-details-marker { display: none; }
.kt-num { font-weight: 600; opacity: 0.55; min-width: 1.2em; }
.kt-icon { font-size: 1.1rem; }
.kt-text { flex: 1; }
.kt-text code, .kt-body code { font-size: 0.82rem; opacity: 0.7; }
.kt-rows { white-space: nowrap; font-variant-numeric: tabular-nums; }
.kt-bar { width: 90px; height: 8px; border-radius: 4px;
  background: color-mix(in srgb, currentColor 10%, transparent); overflow: hidden; }
.kt-bar span { display: block; height: 100%; background: #0a6ebd; }
.kt-more .kt-bar span { background: #e8590c; }
.kt-body { min-width: 0; display: flex; flex-direction: column; gap: 8px; margin-left: 2.4em; }
.kt-chip { display: inline-block; padding: 0 6px; margin: 1px 2px; border-radius: 10px;
  font-size: 0.8rem; background: color-mix(in srgb, currentColor 8%, transparent); }
.kt-added { background: rgba(10, 110, 189, 0.18); }
.kt-warn { padding: 4px 8px; border-radius: 6px; background: rgba(232, 89, 12, 0.16); }
.kt-muted { opacity: 0.6; font-size: 0.82rem; }
.kt-body pre { margin: 0; padding: 6px 8px; border-radius: 6px; white-space: pre-wrap;
  background: color-mix(in srgb, currentColor 6%, transparent); font-size: 0.8rem; }
.kt-scroll { overflow-x: auto; max-width: 100%; }
.kt-body table { border-collapse: collapse; font-size: 0.82rem; }
.kt-body th, .kt-body td { padding: 2px 8px; text-align: left;
  border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
.kt-body td.kt-n { text-align: right; font-variant-numeric: tabular-nums; }
.kt-body .kt-added-cell { background: rgba(10, 110, 189, 0.10); }
</style>
"""


def _n(value) -> str:
    """A count with thin spaces : 10 024."""
    return f"{value:,}".replace(",", " ") if value is not None else ""


def _e(text) -> str:
    return html.escape(str(text))


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    if isinstance(value, int) and not isinstance(value, bool):
        return _n(value)
    return _e(value)


def _table(
    frame: pl.DataFrame, highlight=(), first=(), max_columns=SAMPLE_COLUMNS
) -> str:
    """A small html table of at most `max_columns` : a wide table shows first the
    columns `first` (those the step uses) and `highlight` (those it adds), in the order
    of the table ; the highlighted ones are colored."""
    columns = frame.columns
    if len(columns) > max_columns:
        keep = set(first) | set(highlight)
        columns = [c for c in columns if c in keep]
        columns += [c for c in frame.columns if c not in keep]
    shown, hidden = columns[:max_columns], columns[max_columns:]
    numeric = {c for c in shown if frame.schema[c].is_numeric()}
    head = "".join(
        f'<th class="{"kt-added-cell" if c in highlight else ""}">{_e(c)}</th>'
        for c in shown
    )
    rows = []
    for row in frame.select(shown).iter_rows(named=True):
        cells = "".join(
            f'<td class="{"kt-n " if c in numeric else ""}'
            f'{"kt-added-cell" if c in highlight else ""}">{_cell(row[c])}</td>'
            for c in shown
        )
        rows.append(f"<tr>{cells}</tr>")
    more = (
        f'<div class="kt-muted" title="{_e(", ".join(hidden))}">'
        f"+ {len(hidden)} more columns</div>"
        if hidden
        else ""
    )
    return (
        f'<div class="kt-scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>'
        f"{more}"
    )


def _columns(result: StepResult) -> str:
    added, removed = result.columns_added, result.columns_removed
    parts = [
        f'<span class="kt-chip kt-added" title="a new column">+ {_e(c)}</span>'
        for c in added
    ]
    if removed:
        names = ", ".join(removed)
        label = _e(removed[0]) if len(removed) == 1 else f"{len(removed)} columns"
        parts.append(
            f'<span class="kt-chip" title="left out : {_e(names)}">− {label}</span>'
        )
    return f"<div>{''.join(parts)}</div>" if parts else ""


def _filter(detail: dict) -> str:
    rows = "".join(
        f'<tr><td><code>{_e(t["condition"])}</code></td>'
        f'<td class="kt-n">{_n(t["removed"])}</td></tr>'
        for t in detail["terms"]
    )
    return (
        f'<div class="kt-muted">each condition alone, on the {_n(detail["rows"])} '
        f"rows of the step</div>"
        f"<table><tr><th>Condition</th><th>Rows removed</th></tr>{rows}</table>"
    )


def _joins(joins: list[dict]) -> str:
    parts = []
    for join in joins:
        before, after = join["rows_before"], join["rows_after"]
        line = (
            f'<code>{_e(join["side"])} JOIN {_e(join["table"])} ON {_e(join["on"])}</code>'
            f" : {_n(before)} → {_n(after)} rows"
        )
        if join["rows_other"] is not None:
            line += f' <span class="kt-muted">({_n(join["rows_other"])} rows in '
            line += f'{_e(join["table"])})</span>'
        parts.append(f"<div>{line}</div>")
        if before and after > before:
            parts.append(
                f'<div class="kt-warn">⚠️ The join multiplies the rows '
                f"(×{after / before:.2f}) : a row found several matches, its amounts "
                f"are now counted several times.</div>"
            )
        elif after < before:
            parts.append(
                f'<div class="kt-muted">{_n(before - after)} rows without a match '
                f"left out</div>"
            )
    return "".join(parts)


def _groups(detail: dict) -> str:
    return (
        f'<div>{_n(detail["groups"])} groups, from {_n(detail["min"])} to '
        f'{_n(detail["max"])} rows each ; the largest :</div>'
        + _table(detail["largest"], highlight=("rows",))
    )


def _step(number: int, result: StepResult, largest: int, detail: bool) -> str:
    step = result.step
    icon, tooltip = ICONS.get(step.kind, ICONS["select"])
    kinds = ", ".join(ICONS.get(k, ICONS["select"])[0] + " " + k for k in step.kinds)
    title = step.comment or ("The result" if step.name == RESULT else step.name)
    rows = (
        f"{_n(result.rows_in)} → {_n(result.rows_out)} rows"
        if result.rows_in is not None
        else f"{_n(result.rows_out)} rows"
    )
    more = result.rows_in is not None and result.rows_out > result.rows_in
    width = 100 * result.rows_out / largest if largest else 0
    body = [_columns(result)]
    if detail:
        body.append(f"<pre>{_e(step.shown or step.sql)}</pre>")
        found = result.detail
        if "filter" in found:
            body.append(_filter(found["filter"]))
        if "join" in found:
            body.append(_joins(found["join"]))
        if "group" in found:
            body.append(_groups(found["group"]))
        for error in found.get("errors", []):
            body.append(f'<div class="kt-muted">not measured : {_e(error)}</div>')
    body.append(
        f'<div class="kt-muted">the first {result.sample.height} rows</div>'
        + _table(result.sample, highlight=result.columns_added, first=step.used)
    )
    return (
        f'<details class="kt-step{" kt-more" if more else ""}"'
        f'{" open" if step.name == RESULT else ""}>'
        f"<summary>"
        f'<span class="kt-num">{number}</span>'
        f'<span class="kt-icon" title="{_e(tooltip)} ({_e(kinds)})">{icon}</span>'
        f'<span class="kt-text"><b>{_e(title)}</b> <code>{_e(step.name)}</code></span>'
        f'<span class="kt-rows" title="rows read → rows kept">{rows}</span>'
        f'<span class="kt-bar" title="the size of the table along the steps">'
        f'<span style="width:{width:.1f}%"></span></span>'
        f"</summary>"
        f'<div class="kt-body">{"".join(body)}</div>'
        f"</details>"
    )


def render(results: list[StepResult], detail: bool = False) -> str:
    """The html of the steps ; `detail` : the SQL and the measures of each step."""
    largest = max(
        [r.rows_out for r in results] + [r.rows_in or 0 for r in results] or [0]
    )
    steps = "".join(
        _step(i, result, largest, detail) for i, result in enumerate(results, 1)
    )
    return f'{STYLE}<div class="kt-steps">{steps}</div>'
