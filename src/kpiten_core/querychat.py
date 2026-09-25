"""Ask a KPI, or a whole panel, in words : « only the Export team », « without the
cancelled orders ».

The model turns the question into SQL filters (the condition of a `WHERE`) :
- on a tile (`ask`) : one filter on the table of the tile, which is computed again on
  the rows it keeps ;
- on a panel (`ask_panel`) : one filter per table it names ; the other tables of the
  panel follow through their many2one (`narrow_store`) : the lines of an order follow
  the order, an order follows its lines.
Nothing else changes : the rights of the user (the rows and columns of their store),
the period and the dimensions of the panel still apply.

What the model is told of a table follows the level of `kt.config`
(`kpiten_core.anonymize`) : its columns, or figures and a few rows with pseudonyms.
The pseudonyms of its answer (`Customer 12`) are put back before a filter is checked
(`sqltile.check_where` : no other table, no file) and tried on the rows.
"""

import datetime
import json
import re
from dataclasses import dataclass, field

import polars as pl

from kpiten_core import anonymize, env, llm, sqltile
from kpiten_core.store import DFStorage

ATTEMPTS = 2  # the model may fix its filter once, from the error it caused
HISTORY = 6  # messages of the conversation sent again

# what the model answers
FILTER, CLEAR, NONE = "filter", "clear", "none"


@dataclass
class Reply:
    text: str  # the answer shown to the user (real names)
    action: str = NONE  # FILTER : new filters ; CLEAR : back to all the rows
    filters: dict[str, str] = field(default_factory=dict)  # table -> where, checked
    title: str | None = None  # a few words : « Export team »
    error: str | None = None
    exchange: list[dict] = field(default_factory=list)  # as the model saw it

    @property
    def where(self) -> str | None:
        """The filter of a tile (its only table)."""
        return next(iter(self.filters.values()), None)


def tile_text(line: dict) -> str:
    """What the model is told of the tile : its name, kind and definition."""
    return (
        f"The KPI « {line.get('name')} » ({line.get('kind')}) on the table "
        f"{line.get('model')}, defined as :\n{line.get('content') or ''}"
    )


SQL_RULES = """polars SQL, like PostgreSQL : double quotes around every column
("partner_id", "partner_id.country_id"), single quotes around a text ; a date is
written DATE '2026-01-31'. A many2one column `x` holds the name, `x_` its id. Use
only the columns below, and the values as they are written below."""


def _head(what: str, today: datetime.date, lang: str) -> str:
    language = f"the language {lang}" if lang else "the language of the question"
    return f"""You help a user of KpiTen (a dashboard on top of Odoo) look at {what}.
The user asks, in words, to narrow the rows it is computed on. Today is {today}.
The period and the filters of the dashboard are already applied : do not filter on a
date unless the question asks for it. "title" and "answer" are written in {language}.
"""


def system_prompt(
    tile: str, description: str, today: datetime.date, lang: str = ""
) -> str:
    return _head("one KPI", today, lang) + f"""
Answer with ONE json object, nothing else :
{{"action": "filter", "where": "<SQL condition>", "title": "<2 to 5 words>",
 "answer": "<one sentence for the user>"}}
- "filter" : "where" is the condition of a SQL WHERE on the table, in {SQL_RULES}
  It replaces the previous filter : repeat what should stay.
- "clear" : the user wants the whole KPI back (no "where").
- "none" : the question is not a filter (explain in "answer" what you can do).

{tile}

The columns of the table :
{description}"""


def panel_prompt(
    panel: str, descriptions: dict[str, str], today: datetime.date, lang: str = ""
) -> str:
    tables = "\n\n".join(
        f"## Table {name}\n{text}" for name, text in descriptions.items()
    )
    return _head(f"a dashboard panel « {panel} »", today, lang) + f"""
Answer with ONE json object, nothing else :
{{"action": "filter", "filters": {{"<table>": "<SQL condition>"}},
 "title": "<2 to 5 words>", "answer": "<one sentence for the user>"}}
- "filter" : "filters" gives the condition of a SQL WHERE for the tables that have the
  columns the question needs, usually ONE table, in {SQL_RULES}
  The other tables follow through their links : filter the orders, their lines
  follow ; filter the lines (a product), the orders that have one follow.
  It replaces the previous filters : repeat what should stay.
- "clear" : the user wants the whole panel back (no "filters").
- "none" : the question is not a filter (explain in "answer" what you can do).

The tables of the panel :

{tables}"""


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


# ---- a panel : the tables follow each other through their many2one
def relations(db: str, tables) -> dict[str, dict[str, str]]:
    """The many2one of each table : table -> {field: related model} (the fields
    metadata the sync wrote)."""
    found = {}
    with env.db_scope(db):
        for table in tables:
            meta = DFStorage.read_meta(table)
            found[table] = {
                name: spec["rel"]
                for name, spec in meta.items()
                if isinstance(spec, dict)
                and spec.get("type") == "many2one"
                and spec.get("rel")
            }
    return found


def links(table: str, filtered, schemas: dict, rels: dict) -> list[tuple]:
    """How `table` follows the filtered tables : (filtered table, column of `table`,
    column of the filtered one) per link, a semi-join on each.

    Its many2one to a filtered table first (a line follows its order : `order_id_` in
    the ids of the orders) ; without one, the many2one of a filtered table to it (an
    order follows its lines : `id` in their `order_id_`)."""
    columns = schemas[table]
    forward = [
        (other, f"{name}_", "id")
        for name, rel in rels.get(table, {}).items()
        for other in filtered
        if rel == other and f"{name}_" in columns
    ]
    if forward:
        return forward
    return [
        (other, "id", f"{name}_")
        for other in filtered
        for name, rel in rels.get(other, {}).items()
        if rel == table and f"{name}_" in schemas[other]
    ]


def narrow_store(
    store: dict, filters: dict[str, str], rels: dict, tables=None
) -> tuple:
    """(the store with the filters of a panel, the tables that followed) : each filter
    on its table, then the other tables of the panel (`tables`, else all of the store)
    through their links (one step)."""
    if not filters:
        return store, {}
    narrowed = dict(store)
    for table, where in filters.items():
        if table in store:
            narrowed[table] = apply(store[table].lazy(), where)
    filtered = [t for t in filters if t in store]
    schemas = {t: store[t].lazy().collect_schema().names() for t in store}
    followed = {}
    for table in tables if tables is not None else store:
        if table in filters or table not in store:
            continue
        joins = links(table, filtered, schemas, rels)
        if not joins:
            continue
        frame = store[table].lazy()
        for other, mine, theirs in joins:
            keys = narrowed[other].select(pl.col(theirs).alias(mine)).drop_nulls()
            frame = frame.join(keys.unique(), on=mine, how="semi")
        narrowed[table] = frame
        followed[table] = sorted({other for other, _m, _t in joins})
    return narrowed, followed


# ---- the conversation
def _converse(provider, system, history, question, anon, complete, read) -> Reply:
    """Ask the model ; `read(data, anon)` turns its json object into (filters, title)
    or raises : the error goes back to the model once."""
    question = anon.hide(question)
    messages = [*history[-HISTORY:], {"role": "user", "content": question}]
    error = None
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
            filters = read(data)
            title = anon.reveal(str(data.get("title") or "")).strip()
            title = title or " ; ".join(filters.values())
            return Reply(answer, FILTER, filters, title[:60], exchange=exchange)
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
        anon.hide(tile_text(line)), description, today or datetime.date.today(), lang
    )

    def read(data: dict) -> dict[str, str]:
        where = anon.reveal(str(data.get("where") or "")).strip()
        if not where:
            raise ValueError('"where" is empty')
        return {line["model"]: try_where(frame, where)}

    return _converse(provider, system, history, question, anon, complete, read)


def ask_panel(
    provider: llm.Provider,
    panel: str,
    frames: dict[str, pl.LazyFrame],
    descriptions: dict[str, str],
    history: list[dict],
    question: str,
    anon: anonymize.Anonymizer | None = None,
    today: datetime.date | None = None,
    complete=llm.complete,
    lang: str = "",
) -> Reply:
    """The filters the question asks for, one per table the model names, each one
    checked and tried on the rows of its table (`frames` : the tables of the panel).

    `anon` : one for all the tables (`anonymize.Anonymizer(shared=...)`), so that a
    pseudonym means the same customer in every table."""
    anon = anon or anonymize.Anonymizer(hide=False)
    system = panel_prompt(panel, descriptions, today or datetime.date.today(), lang)

    def read(data: dict) -> dict[str, str]:
        wanted = data.get("filters")
        if not isinstance(wanted, dict) or not wanted:
            raise ValueError('"filters" must give a condition for at least one table')
        filters = {}
        for table, where in wanted.items():
            if table not in frames:
                known = ", ".join(frames)
                raise ValueError(f"unknown table {table!r} (the tables : {known})")
            where = anon.reveal(str(where or "")).strip()
            if where:
                filters[table] = try_where(frames[table], where)
        if not filters:
            raise ValueError('"filters" is empty')
        return filters

    return _converse(provider, system, history, question, anon, complete, read)
