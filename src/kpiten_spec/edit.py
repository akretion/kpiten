"""Change the top keys of a TOML definition, line by line : what a form (the tile
builder of Odoo) changes is rewritten, the rest is kept as it is written (comments,
blank lines, order, the sections `[labels]`, `[plotly.layout]`...).

Standard library only, like the rest of kpiten-spec.
"""

from __future__ import annotations

import re
from typing import Any

from kpiten_spec.spec import tomllib

# a section header (`[table]`, `[[x]]`) : the top keys are the lines above the first one
SECTION_RE = re.compile(r"^\s*\[")
KEY_RE = re.compile(r"""^\s*(?:"([^"]+)"|'([^']+)'|([\w-]+))\s*=""")


def dump(value: Any) -> str:
    """A TOML value : a string (multiline when it has line breaks), an integer, a
    float or a boolean."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if "\n" in text and '"""' not in text:
        return '"""\n' + text.replace("\\", "\\\\") + '"""'
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _key(line: str) -> str | None:
    match = KEY_RE.match(line)
    return next((g for g in match.groups() if g), None) if match else None


def _entry_end(lines: list[str], start: int) -> int:
    """The index after the last line of the entry starting at `start` : a multiline
    string or array goes on until the lines up to it parse."""
    for end in range(start + 1, len(lines) + 1):
        try:
            tomllib.loads("\n".join(lines[start:end]))
            return end
        except tomllib.TOMLDecodeError:
            continue
    return start + 1


def _comment(line: str) -> str:
    """The comment at the end of a one line entry (`  # the x axis`), or ''."""
    for pos, char in enumerate(line):
        if char != "#":
            continue
        try:
            tomllib.loads(line[:pos])
        except tomllib.TOMLDecodeError:
            continue  # a # inside the value
        return "  " + line[pos:].strip()
    return ""


def set_keys(text: str, changes: dict[str, Any]) -> str:
    """`text` with its top keys set to the values of `changes` ; a value None removes
    the key. A key already there keeps its place and its comment, a new one comes after
    the other top keys (before the first section)."""
    lines = (text or "").split("\n")
    top = next((i for i, line in enumerate(lines) if SECTION_RE.match(line)), None)
    top = len(lines) if top is None else top
    head, tail = lines[:top], lines[top:]
    changes = dict(changes)
    out: list[str] = []
    i = 0
    while i < len(head):
        key = _key(head[i])
        if key is None or key not in changes:
            out.append(head[i])
            i += 1
            continue
        end = _entry_end(head, i)
        value = changes.pop(key)
        if value is not None:
            comment = _comment(head[i]) if end == i + 1 else ""
            out.append(f"{_name(key)} = {dump(value)}{comment}")
        i = end
    new = [f"{_name(k)} = {dump(v)}" for k, v in changes.items() if v is not None]
    if new:  # after the last top key, the blank lines before a section kept
        last = max((n for n, line in enumerate(out) if line.strip()), default=-1)
        out[last + 1 : last + 1] = new
    if tail and out and out[-1].strip():
        out.append("")  # a blank line before the first section
    result = "\n".join(out + tail)
    return result.strip("\n") + "\n" if result.strip() else ""


def _name(key: str) -> str:
    return key if re.fullmatch(r"[\w-]+", key) else f'"{key}"'
