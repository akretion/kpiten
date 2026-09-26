"""KpiTen plugin : derived tables, a SQL made of CTE run step by step on the rows of the
user and explained (see `docs/kpiten-tables-derivees.md` of bi/).

    from derived_kpiten import render, split, trace

    results = trace(split(sql), user_store)
    html = render(results, detail=is_manager)

It reads no store : the front gives it the tables of the user, already restricted to
what the user may read.
"""

from .render import render
from .steps import RESULT, Step, StepResult, split, trace

__all__ = ["RESULT", "Step", "StepResult", "render", "split", "trace"]
