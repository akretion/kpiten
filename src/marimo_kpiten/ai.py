"""The AI of the explorer : it writes polars, the sandbox of kpiten-core runs it.

What the model sees : the name and type of the columns of the table the user chose
and, unless `AI_SEND_VALUES=0`, the values of the columns that have few of them
(state, country...). No row. What it answers is checked and run by
`kpiten_core.sandbox` on the table of the user, whose rows and columns are already
restricted to their rights : only the errors of the code go back to the model.

Two providers, each one shown only when configured (see `.env.example`) :
Claude (`ANTHROPIC_API_KEY`) and a local model behind an OpenAI-compatible api
(`LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`) : with it nothing leaves the machine.
"""

import difflib
import re
from dataclasses import dataclass, field

import polars as pl
import requests

from kpiten_core import env, sandbox

ALLOWED = sorted(sandbox.PL_FUNCS | sandbox.DF_METHODS | sandbox.EXPR_METHODS)
MAX_ROWS = 1000  # rows of an answer
MAX_VALUES = 12  # values listed for a column
VALUE_CHARS = 40
SAMPLE_ROWS = 200_000  # rows looked at to list the values
ATTEMPTS = 2  # the model may fix its code once, from the error it caused
TIMEOUT = 120  # seconds to wait for the model


@dataclass
class Provider:
    key: str
    label: str
    model: str
    leaves_machine: bool  # what is sent goes to a third party


def providers() -> dict[str, Provider]:
    """The providers that are configured, by key."""
    found = {}
    if env.get("ANTHROPIC_API_KEY"):
        model = env.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        found["anthropic"] = Provider("anthropic", f"Claude ({model})", model, True)
    if env.get("LOCAL_LLM_MODEL"):
        model = env.get("LOCAL_LLM_MODEL")
        found["local"] = Provider("local", f"Local ({model})", model, False)
    return found


def complete(provider: Provider, system: str, messages: list[dict]) -> str:
    """The text answer of the model to a conversation."""
    if provider.key == "anthropic":
        import anthropic

        client = anthropic.Anthropic(
            api_key=env.get("ANTHROPIC_API_KEY"), timeout=TIMEOUT
        )
        reply = client.messages.create(
            model=provider.model, max_tokens=2000, system=system, messages=messages
        )
        return "".join(block.text for block in reply.content if block.type == "text")
    url = env.get("LOCAL_LLM_URL", "http://localhost:11434/v1").rstrip("/")
    reply = requests.post(
        f"{url}/chat/completions",
        json={
            "model": provider.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
        },
        timeout=TIMEOUT,
    )
    reply.raise_for_status()
    return reply.json()["choices"][0]["message"]["content"]


def known_values(frame: pl.LazyFrame) -> dict[str, list[str]]:
    """The values of the text and boolean columns that have few of them, seen in the
    first rows (a column with more is not listed)."""
    schema = frame.collect_schema()
    columns = [c for c, t in schema.items() if t in (pl.String, pl.Boolean)]
    if not columns:
        return {}
    sample = frame.head(SAMPLE_ROWS)
    counts = sample.select(
        [pl.col(c).drop_nulls().n_unique().alias(c) for c in columns]
    ).collect()
    few = [c for c in columns if 0 < counts[c][0] <= MAX_VALUES]
    if not few:
        return {}
    values = sample.select(
        [pl.col(c).drop_nulls().unique().sort().implode().alias(c) for c in few]
    ).collect()
    return {c: [str(v)[:VALUE_CHARS] for v in values[c][0]] for c in few}


def sends_values() -> bool:
    """Whether the few values of a column go to the model (`AI_SEND_VALUES=0` : no)."""
    return env.get("AI_SEND_VALUES", "1") != "0"


def describe(frame: pl.LazyFrame, send_values: bool | None = None) -> str:
    """What the model is told about the table : its columns, with their few values."""
    if send_values is None:
        send_values = sends_values()
    values = known_values(frame) if send_values else {}
    lines = []
    for column, dtype in frame.collect_schema().items():
        line = f"- {column} : {dtype}"
        if column in values:
            line += " ; values : " + ", ".join(repr(v) for v in values[column])
        lines.append(line)
    return "\n".join(lines)


def system_prompt(description: str) -> str:
    return f"""You are a data analyst in KpiTen, an analytics tool on top of Odoo. The user
explores one table, already restricted to the rows and columns they may read.

Answer with a short explanation (a few sentences, in the language of the question) and
then ONE ```python block. The code :
- works on `d`, a polars LazyFrame of the table, and on `pl` (polars) ;
- assigns its answer to `d_next` : a table of at most {MAX_ROWS} rows, sorted, with
  readable column names ;
- has no import, def, lambda, loop, try or with ; reads no file and does no SQL ;
- calls only these functions and methods : {", ".join(ALLOWED)}.
A column such as `partner_id.name` is written pl.col("partner_id.name"). A many2one `x`
holds the name and `x_` (with an underscore) its id. Amounts may be decimals : cast to
pl.Float64 before a ratio. If the question needs no code, answer without a block.

Examples of the style :
d_next = d.group_by("state").agg(pl.len().alias("orders")).sort("orders", descending=True)
d_next = d.group_by(pl.col("date_order").dt.truncate("1mo").alias("month")).agg(pl.col("amount_untaxed").sum().alias("total")).sort("month")

The columns of the table :
{description}"""


def extract_code(text: str) -> tuple[str, str | None]:
    """(explanation, code) : the python block of an answer, None without one."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if not match:
        return text.strip(), None
    explanation = (text[: match.start()] + text[match.end() :]).strip()
    return explanation, match.group(1).strip()


def hint(error: str) -> str:
    """For a refused call, the allowed names that look like it
    (`forbidden call: with_column` -> `Did you mean : with_columns ?`)."""
    refused = re.search(r"forbidden (?:call|method|attribute): (\w+)", error)
    close = difflib.get_close_matches(refused.group(1), ALLOWED, n=3) if refused else []
    return f" Did you mean : {', '.join(close)} ?" if close else ""


def run(code: str, frame: pl.LazyFrame) -> pl.DataFrame:
    """The table the code computes, checked and run by the sandbox."""
    out = sandbox.run(code, frame, "d", "d_next")
    if isinstance(out, pl.LazyFrame):
        out = out.head(MAX_ROWS).collect(engine="streaming")
    return out.head(MAX_ROWS)


@dataclass
class Answer:
    text: str
    code: str | None = None
    table: pl.DataFrame | None = None
    error: str | None = None
    exchange: list[dict] = field(default_factory=list)  # to keep in the conversation


def ask(provider, frame, description, history, question, complete=complete) -> Answer:
    """The answer to a question : the model writes code, the sandbox runs it, and the
    model gets one more try when the code was refused or failed."""
    system = system_prompt(description)
    messages = [*history, {"role": "user", "content": question}]
    text = explanation = code = error = None
    for _attempt in range(ATTEMPTS):
        try:
            text = complete(provider, system, messages)
        except Exception as err:
            return Answer(f"The model could not answer : {err}", error=str(err))
        explanation, code = extract_code(text)
        exchange = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": text},
        ]
        if code is None:  # a text answer
            return Answer(explanation, exchange=exchange)
        try:
            return Answer(explanation, code, run(code, frame), exchange=exchange)
        except Exception as err:
            error = f"{type(err).__name__} : {err}"[:500]
            messages += [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"The code failed : {error}.{hint(error)}\nAnswer again "
                    "with the corrected python block.",
                },
            ]
    return Answer(explanation, code, error=error, exchange=exchange)
