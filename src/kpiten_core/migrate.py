"""Rewrite the tile definitions of Odoo data files in the syntax version 2 (`spec`).

    python -m kpiten_core.migrate FILE.xml [FILE.xml ...]

Only the text of the `definition` field of the card, graph and pivot tiles changes (a
union, a data tile, a version 2 one : untouched) ; the rest of the file stays as it is.
The keys are written in the order of the schema, and the comment at the end of a line
is kept when its key keeps its name.
"""

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from kpiten_core import serial, spec

RECORD_RE = re.compile(
    r'(<record id="[^"]+" model="kt\.dataset\.line">)(.*?)(</record>)', re.S
)
KIND_RE = re.compile(r'<field name="kind">(\w+)</field>')
DEFINITION_RE = re.compile(r'(<field name="definition">)(.*?)(</field>)', re.S)
COMMENT_RE = re.compile(r"^\s*([\w.]+)\s*=[^#\n]*?(\s*#.*)$", re.M)


def ordered(data: dict, entries) -> dict:
    """`data` with its keys in the order of the schema (its tables too)."""
    result = {}
    for entry in entries:
        if entry.name not in data:
            continue
        value = data[entry.name]
        if isinstance(entry, spec.Table) and isinstance(value, dict) and entry.keys:
            value = ordered(value, entry.keys)
        result[entry.name] = value
    result.update({k: v for k, v in data.items() if k not in result})
    return result


def to_v2(text: str, kind: str) -> str:
    """A version 1 definition in version 2, as TOML."""
    comments = dict(COMMENT_RE.findall(text))
    data = ordered(spec.load(text, kind), spec.KINDS[kind].entries)
    lines = serial.dumps(data).rstrip("\n").split("\n")
    for i, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if key in comments and "=" in line:
            lines[i] = line + comments[key]
    return "\n".join(lines) + "\n"


def migrate(source: str) -> tuple[str, int]:
    """The content of a data file with its definitions in version 2, and how many."""
    count = 0

    def record(match):
        nonlocal count
        head, body, tail = match.groups()
        kind = KIND_RE.search(body)
        definition = DEFINITION_RE.search(body)
        if not kind or not definition or kind.group(1) not in spec.KINDS:
            return match.group(0)
        text = unescape(definition.group(2))
        if spec.is_v2(serial.loads(text)):
            return match.group(0)
        count += 1
        new = escape(to_v2(text, kind.group(1)))
        body = body[: definition.start(2)] + new + body[definition.end(2) :]
        return head + body + tail

    return RECORD_RE.sub(record, source), count


def main(paths: list[str]) -> None:
    for name in paths:
        path = Path(name)
        content, count = migrate(path.read_text())
        if count:
            path.write_text(content)
        print(f"{path} : {count} definition(s) in version {spec.VERSION}")


if __name__ == "__main__":
    main(sys.argv[1:])
