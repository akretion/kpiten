"""The AI of the explorer : it writes polars, the sandbox of kpiten-core runs it.

What the model sees depends on the level of `kt.config` (`kpiten_core.anonymize`) :
the columns only, or figures on them and a few rows, with the people and the
products renamed (`Customer 12`), or the same in clear for a local model. What it
answers is revealed (the pseudonyms put back), checked and run by
`kpiten_core.sandbox` on the table of the user, whose rows and columns are already
restricted to their rights : only the errors of the code go back to the model.

Two providers, each one shown only when configured (see `.env.example`) :
Claude (`ANTHROPIC_API_KEY`) and a local model behind an OpenAI-compatible api
(`LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`) : with it nothing leaves the machine.
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from kpiten_core import anonymize, config, env, sandbox
from kpiten_core.llm import Provider, complete, providers  # noqa: F401

SKILLS_DIR = Path(__file__).parent / "skills"
ALLOWED = sorted(sandbox.PL_FUNCS | sandbox.DF_METHODS | sandbox.EXPR_METHODS)
MAX_ROWS = 1000  # rows of an answer
ATTEMPTS = 2  # the model may fix its code once, from the error it caused


def enabled() -> bool:
    """The AI is on unless `kt.config` (Odoo) turns it off for everyone."""
    return config.ai_enabled()


def send_level() -> str:
    """What the model is told of a table (`anonymize.LEVELS`) : the level of
    `kt.config` ; `AI_SEND_VALUES=0` in the environment lowers it to `schema`."""
    if env.get("AI_SEND_VALUES", "1") == "0":
        return "schema"
    return config.ai_send_level()


def sends_values() -> bool:
    return send_level() != "schema"


def describe(
    frame: pl.LazyFrame,
    anon: anonymize.Anonymizer | None = None,
    level: str | None = None,
) -> str:
    """What the model is told about the table : its columns, figures on them and a
    few rows, with pseudonyms (`kpiten_core.anonymize`)."""
    level = level or send_level()
    if anon is None:
        anon = anonymize.Anonymizer(hide=level != "clear")
    return anonymize.summary(frame, anon, level)


@dataclass
class Skill:
    """A markdown file given to the model : how to write the code, what the words of
    a table mean. Its optional header lists the tables it is for (else all of them) :

        ---
        name: purchase
        tables: purchase.order, purchase.order.line
        ---
    """

    name: str
    tables: list[str]
    body: str


def parse_skill(path: Path) -> Skill:
    text = path.read_text()
    meta = {}
    if text.startswith("---\n"):
        header, _, text = text[4:].partition("\n---\n")
        for line in header.splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    tables = [t.strip() for t in meta.get("tables", "").split(",") if t.strip()]
    return Skill(meta.get("name") or path.stem, tables, text.strip())


def skills_for(table: str) -> list[Skill]:
    """The skills for a table : those of `skills/`, then those of the folder
    `AI_SKILLS_DIR` (the team adds its own there, without touching the code)."""
    folders = [SKILLS_DIR]
    if env.get("AI_SKILLS_DIR"):
        folders.append(Path(env.get("AI_SKILLS_DIR")))
    found = []
    for folder in folders:
        for path in sorted(folder.glob("*.md")):
            skill = parse_skill(path)
            if not skill.tables or table in skill.tables:
                found.append(skill)
    return found


def system_prompt(description: str, skills: list[Skill] | None = None) -> str:
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

The columns of the table :
{description}""" + "".join(
        f"\n\n# Skill : {s.name}\n{s.body}" for s in skills or []
    )


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


def ask(
    provider,
    frame,
    description,
    history,
    question,
    complete=complete,
    skills=None,
    anon: anonymize.Anonymizer | None = None,
) -> Answer:
    """The answer to a question : the model writes code, the sandbox runs it, and the
    model gets one more try when the code was refused or failed.

    With `anon`, the model sees pseudonyms only : the real values the session knows
    are hidden in the question and the history (the code of a KPI to refine), and the
    pseudonyms of its answer are revealed before it is shown and its code run."""
    anon = anon or anonymize.Anonymizer(hide=False)
    system = system_prompt(description, skills)
    question = anon.hide(question)
    history = [{**m, "content": anon.hide(m["content"])} for m in history]
    messages = [*history, {"role": "user", "content": question}]
    text = explanation = code = error = None
    for _attempt in range(ATTEMPTS):
        try:
            text = complete(provider, system, messages)
        except Exception as err:
            return Answer(f"The model could not answer : {err}", error=str(err))
        explanation, code = extract_code(text)
        explanation, code = anon.reveal(explanation), anon.reveal(code)
        exchange = [  # the conversation as the model saw it : with pseudonyms
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
                    "content": f"The code failed : {anon.hide(error)}.{hint(error)}\n"
                    "Answer again with the corrected python block.",
                },
            ]
    return Answer(explanation, code, error=error, exchange=exchange)
