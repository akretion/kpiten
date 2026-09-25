"""Ask a KPI in words : « only the Export team », « without the cancelled orders ».

The model turns the question into a SQL filter (a `WHERE`) on the table of the tile ;
the tile is computed again on the rows it keeps, and the filter is shown to the user.
Nothing else changes : the rights of the user (the rows and columns of their store),
the period and the dimensions of the panel still apply.

What the model is told of the table follows the level of `kt.config`
(`kpiten_core.anonymize`) : its columns, or figures and a few rows with pseudonyms.
The pseudonyms of its answer (`Customer 12`) are put back before the filter is checked
(`sqltile.check_where` : no other table, no file) and tried on the rows.
"""

import datetime
import json
import re
from dataclasses import dataclass, field

import polars as pl

from kpiten_core import anonymize, llm, sqltile

ATTEMPTS = 2  # the model may fix its filter once, from the error it caused
HISTORY = 6  # messages of the conversation sent again

# what the model answers
FILTER, CLEAR, NONE = "filter", "clear", "none"


@dataclass
class Reply:
    text: str  # the answer shown to the user (real names)
    action: str = NONE  # FILTER : a new `where` ; CLEAR : back to the whole tile
    where: str | None = None  # checked and tried, real names
    title: str | None = None  # a few words : « Export team »
    error: str | None = None
    exchange: list[dict] = field(default_factory=list)  # as the model saw it


def tile_text(line: dict) -> str:
    """What the model is told of the tile : its name, kind and definition."""
    return (
        f"The KPI « {line.get('name')} » ({line.get('kind')}) on the table "
        f"{line.get('model')}, defined as :\n{line.get('content') or ''}"
    )


def system_prompt(
    tile: str, description: str, today: datetime.date, lang: str = ""
) -> str:
    language = f"the language {lang}" if lang else "the language of the question"
    return f"""You help a user of KpiTen (a dashboard on top of Odoo) look at one KPI.
The user asks, in words, to narrow the rows the KPI is computed on. Today is {today}.
The period and the filters of the dashboard are already applied : do not filter on a
date unless the question asks for it.

Answer with ONE json object, nothing else :
{{"action": "filter", "where": "<SQL condition>", "title": "<2 to 5 words>",
 "answer": "<one sentence for the user>"}}
"title" and "answer" are written in {language}.
- "filter" : "where" is the condition of a SQL WHERE on the table (polars SQL,
  like PostgreSQL) : double quotes around every column ("partner_id",
  "partner_id.country_id"), single quotes around a text ; a date is written
  DATE '2026-01-31'. It replaces the previous filter : repeat what should stay.
- "clear" : the user wants the whole KPI back (no "where").
- "none" : the question is not a filter (explain in "answer" what you can do).
A many2one column `x` holds the name, `x_` its id. Use only the columns below, and
the values as they are written below.

{tile}

The columns of the table :
{description}"""


def parse(text: str) -> dict:
    """The json object of an answer (in a ```json block or not)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("the answer holds no json object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("the answer is not a json object")
    return data


def quote_columns(where: str, columns) -> str:
    """The columns with a dot (`partner_id.country_id`) put in double quotes where the
    model forgot them : unquoted, SQL reads a field of a struct."""
    for column in sorted((c for c in columns if "." in c), key=len, reverse=True):
        where = re.sub(
            r'(?<![\w."])' + re.escape(column) + r'(?![\w."])', f'"{column}"', where
        )
    return where


def try_where(frame: pl.LazyFrame, where: str) -> str:
    """The `where` once checked (no other table, no file) and run on a few rows."""
    where = sqltile.check_where(quote_columns(where, frame.collect_schema().names()))
    frame.sql(f"SELECT * FROM self WHERE {where}").head(1).collect()
    return where


def apply(frame: pl.LazyFrame, where: str | None) -> pl.LazyFrame:
    """The rows of the table the filter keeps (all of them without one)."""
    if not where:
        return frame
    return frame.sql(f"SELECT * FROM self WHERE {sqltile.check_where(where)}")


def ask(
    provider: llm.Provider,
    line: dict,
    frame: pl.LazyFrame,
    description: str,
    history: list[dict],
    question: str,
    anon: anonymize.Anonymizer | None = None,
    today: datetime.date | None = None,
    complete=llm.complete,
    lang: str = "",
) -> Reply:
    """The filter the question asks for, checked and tried on the rows of the tile.

    `history` is the conversation as the model saw it (with pseudonyms) ; the `anon`
    of the table hides the real values of the question and reveals the answer ; `lang`
    (`fr_FR`) : the language of the user in Odoo, the one of the answer."""
    anon = anon or anonymize.Anonymizer(hide=False)
    system = system_prompt(
        anon.hide(tile_text(line)),
        description,
        today or datetime.date.today(),
        lang,
    )
    question = anon.hide(question)
    messages = [*history[-HISTORY:], {"role": "user", "content": question}]
    error = None
    exchange: list[dict] = []
    for _attempt in range(ATTEMPTS):
        try:
            text = complete(provider, system, messages)
        except Exception as err:
            return Reply(f"The model could not answer : {err}", error=str(err))
        exchange = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": text},
        ]
        try:
            data = parse(text)
            action = data.get("action") or NONE
            answer = anon.reveal(str(data.get("answer") or "")).strip()
            if action == CLEAR:
                return Reply(answer, CLEAR, exchange=exchange)
            if action != FILTER:
                return Reply(answer or text, NONE, exchange=exchange)
            where = anon.reveal(str(data.get("where") or "")).strip()
            if not where:
                raise ValueError('"where" is empty')
            where = try_where(frame, where)
            title = anon.reveal(str(data.get("title") or "")).strip() or where
            return Reply(answer, FILTER, where, title[:60], exchange=exchange)
        except Exception as err:
            # the first line : polars adds its whole query plan
            error = f"{type(err).__name__} : {str(err).strip().splitlines()[0]}"[:300]
            messages += [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"That failed : {anon.hide(error)}\n"
                    "Answer again with the corrected json object.",
                },
            ]
    return Reply(f"The filter could not be used : {error}", error=error)
