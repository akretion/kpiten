"""The AI writes a query on the tables of the user, checked by running it.

Two modes : `query`, the result (a short, efficient query : skill `query.md`), and
`steps`, the result explained (a chain of CTE with a comment each : skill `steps.md`).
Both get `sql.md` (the tables, the SQL of polars, the traps of a join).

The model gets the description of the table `d` (what `kpiten_core.anonymize` lets out
at the level of the base : pseudonyms by default), the columns of the tables to join,
the query the user has now and the skills. Its answer is revealed (the pseudonyms put
back) and run on the tables of the user ; an error goes back to the model once.
"""

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from kpiten_core import anonymize
from kpiten_core.llm import complete

from kpiten_core import sqltile
from kpiten_core.derived import run_polars

from .polars_steps import split_polars
from .steps import StepResult, short_error, split, trace

SKILLS = Path(__file__).parent / "skills"
MODES = ("query", "steps")  # the result ; the result explained, step by step
LANGUAGES = ("sql", "polars")
ATTEMPTS = 2  # the model may fix its query once, from the error it caused
OTHER_COLUMNS = 60  # the columns listed of each other table
PREVIEW_ROWS = 5000  # rows of the result collected in the mode `query`


def skill(name: str) -> str:
    text = (SKILLS / f"{name}.md").read_text()
    if text.startswith("---\n"):  # the header of a skill : its name
        text = text[4:].partition("\n---\n")[2]
    return text.strip()


def columns(frame: pl.LazyFrame, limit: int = OTHER_COLUMNS) -> str:
    """The columns of a table and their types, for the tables the query may join."""
    schema = frame.collect_schema()
    shown = [f"{name} ({dtype})" for name, dtype in list(schema.items())[:limit]]
    more = f", and {len(schema) - limit} more" if len(schema) > limit else ""
    return ", ".join(shown) + more


def system_prompt(
    table: str,
    description: str,
    others: dict[str, str],
    today=None,
    mode="steps",
    language="sql",
) -> str:
    """`table` : the name of `d` ; `others` : name -> its columns (`columns()`) ;
    `mode` : `query` (the result) or `steps` (the result explained) ; `language` : `sql`
    or `polars` (one skill for both modes : a comment above each method)."""
    today = today or datetime.date.today()
    other_tables = "\n".join(f'- "{name}" : {cols}' for name, cols in others.items())
    block = (
        "```python block with the whole code"
        if language == "polars"
        else ("```sql block with the whole query")
    )
    skills = (
        skill("polars") if language == "polars" else f"{skill(mode)}\n\n{skill('sql')}"
    )
    return f"""You are a data analyst in KpiTen, an analytics tool on top of Odoo. The user
asks a query on their tables, already restricted to the rows and columns they may
read. Today is {today.isoformat()}.

Answer with a short explanation (two or three sentences, in the language of the
question), then ONE {block}. If the question needs no query, answer without a block.

{skills}

## The table `d` : {table}

{description}

## The other tables it may join (by their name in double quotes)

{other_tables or "none : use `d` only"}"""


def extract_sql(text: str, language: str = "sql") -> tuple[str, str | None]:
    """(explanation, code) : the sql (or python) block of an answer, None without."""
    fence = "(?:python|py)?" if language == "polars" else "(?:sql)?"
    match = re.search(rf"```{fence}\s*\n(.*?)```", text, re.S | re.IGNORECASE)
    if not match:
        return text.strip(), None
    explanation = (text[: match.start()] + text[match.end() :]).strip()
    return explanation, match.group(1).strip()


@dataclass
class Answer:
    text: str
    sql: str | None = None
    results: list[StepResult] | None = None
    error: str | None = None
    exchange: list[dict] = field(default_factory=list)  # as the model saw it
    unknown: list[str] = field(default_factory=list)  # pseudonyms the page forgot
    table: pl.DataFrame | None = None  # the result, in the mode `query`


def message(question: str, current: str = "", anon=None) -> str:
    """What the user asks, as the model sees it : the question and the query the user
    has now, the real values hidden."""
    anon = anon or anonymize.Anonymizer(hide=False)
    content = anon.hide(question)
    if current.strip():
        content += (
            "\n\nThe query the user has now (change it, or start over if the "
            f"question is about something else) :\n```sql\n{anon.hide(current)}\n```"
        )
    return content


def run(
    sql: str, tables: dict, rows: int = PREVIEW_ROWS, language: str = "sql"
) -> pl.DataFrame:
    """The result of a query (or of polars code) : its first `rows` (polars runs it
    lazily, optimized)."""
    if language == "polars":
        others = {k: v for k, v in tables.items() if k != "d"}
        return run_polars(sql, others, tables.get("d")).lazy().head(rows).collect()
    return sqltile.run(sql, tables).head(rows).collect()


def split_code(code: str, language: str = "sql"):
    """The steps of a query, or of polars code."""
    return split_polars(code) if language == "polars" else split(code)


def receive(
    text: str, tables: dict, anon=None, mode: str = "steps", language: str = "sql"
) -> Answer:
    """The answer of a model (by the api, or pasted from a chat) : its sql revealed and
    run on `tables`, step by step or for its result (`mode`) ; `error` when it does not
    run."""
    anon = anon or anonymize.Anonymizer(hide=False)
    explanation, sql = extract_sql(text, language)
    unknown = anon.unknown(sql)  # before revealing : the real values are no pseudonyms
    explanation, sql = anon.reveal(explanation), anon.reveal(sql)
    if sql is None:  # a text answer
        return Answer(explanation)
    if unknown:
        return Answer(
            explanation,
            sql,
            unknown=unknown,
            error="names this page does not know : "
            + ", ".join(unknown)
            + " (the page was reloaded since the prompt was copied ?)",
        )
    try:
        if mode == "query":
            return Answer(explanation, sql, table=run(sql, tables, language=language))
        return Answer(explanation, sql, trace(split_code(sql, language), tables))
    except Exception as err:
        return Answer(
            explanation, sql, error=f"{type(err).__name__} : {short_error(err)}"
        )


def correction(error: str, anon=None, language: str = "sql") -> str:
    """What the model is told of the error of its query."""
    anon = anon or anonymize.Anonymizer(hide=False)
    block = "python" if language == "polars" else "sql"
    return (
        f"The query failed : {anon.hide(error)}\n"
        f"Answer again with the whole corrected {block} block."
    )


def clipboard(system: str, content: str) -> str:
    """The prompt as one text, to paste in a chat (ChatGPT, Mistral, Gemini...) : the
    instructions, then the question."""
    return f"{system}\n\n## The question\n\n{content}"


def ask(
    provider,
    tables: dict,
    system: str,
    question: str,
    current: str = "",
    history: list[dict] | None = None,
    anon: anonymize.Anonymizer | None = None,
    complete=complete,
    mode: str = "steps",
    language: str = "sql",
) -> Answer:
    """The query the model writes for `question`, run step by step on `tables` (with
    `d`) ; `current` : the query the user has now, that the model may change.

    With `anon`, the model sees pseudonyms only : the real values the session knows are
    hidden in what is sent, the pseudonyms of the answer revealed before it runs."""
    anon = anon or anonymize.Anonymizer(hide=False)
    content = message(question, current, anon)
    history = [{**m, "content": anon.hide(m["content"])} for m in history or []]
    messages = [*history, {"role": "user", "content": content}]
    answer = Answer("")
    for _attempt in range(ATTEMPTS):
        try:
            text = complete(provider, system, messages)
        except Exception as err:
            return Answer(f"The model could not answer : {err}", error=str(err))
        answer = receive(text, tables, anon, mode, language)
        answer.exchange = [
            {"role": "user", "content": content},
            {"role": "assistant", "content": text},
        ]
        if answer.error is None or answer.unknown:
            return answer
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": correction(answer.error, anon, language)},
        ]
    return answer


def rewrite(lang: str = "", language: str = "sql") -> str:
    """The question that asks the model to explain the current query step by step
    (mode `steps`) : the same result, in commented CTE (or polars with a comment
    above each method) ; `lang` : the language of the user in Odoo (`fr_FR`)."""
    words = f" Write the comments in the language {lang}." if lang else ""
    form = (
        "one method per line, a comment above each one"
        if language == "polars"
        else "one CTE per operation with its comment"
    )
    return (
        "Rewrite the query I have now step by step, for a reader who learns : the "
        f"same result, {form}." + words
    )
