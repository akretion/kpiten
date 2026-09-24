"""Convert the tile definitions written in the syntax version 1 to the version 2 (`spec`).

The version 1 is no longer read : the tiles written in it are converted once.

    python -m kpiten_core.migrate FILE.xml [FILE.xml ...]   # Odoo data files
    python -m kpiten_core.migrate --db DB                    # the tiles stored in DB

Only the definitions of the card, graph and pivot tiles written in version 1 change (a
union, a data tile, a version 2 one : untouched). In a file, the rest stays as it is ;
the keys are written in the order of the schema, and the comment at the end of a line
is kept when its key keeps its name. In a base, through the backend of `kpiten_core`
(`ODOO_*` of the environment), the account of the backend writes the tiles.
"""

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from kpiten_core import serial, spec

RECORD_RE = re.compile(
    r'(<record id="[^"]+" model="kt\.(?:kpi|dataset\.line)">)(.*?)(</record>)', re.S
)
KIND_RE = re.compile(r'<field name="kind">(\w+)</field>')
DEFINITION_RE = re.compile(r'(<field name="definition">)(.*?)(</field>)', re.S)
COMMENT_RE = re.compile(r"^\s*([\w.]+)\s*=[^#\n]*?(\s*#.*)$", re.M)

# the keys only the version 1 had
LEGACY_KEYS = {
    "card": {"best", "good", "detail_label", "derive"},
    "graph": {"graph_type", "x", "y", "monthly"},
    "pivot": {"index", "column", "monthly"},
}


def is_legacy(data: dict, kind: str) -> bool:
    """Whether a definition is written in version 1."""
    if data.get("version") is not None or kind not in LEGACY_KEYS:
        return False
    if kind == "card" and isinstance(data.get("detail"), str):
        return True
    return bool(LEGACY_KEYS[kind] & set(data))


# ---- version 1 -> version 2 -------------------------------------------------
def upgrade(data: dict, kind: str) -> dict:
    """A version 1 definition in version 2. Raises `ValueError` for what version 2
    cannot say."""
    if kind == "card":
        return _upgrade_card(data)
    if kind == "graph":
        return _upgrade_graph(data)
    if kind == "pivot":
        return _upgrade_pivot(data)
    return data


def _copy(data: dict, *names: str) -> dict:
    return {name: data[name] for name in names if name in data}


def _upgrade_card(data: dict) -> dict:
    new = {"version": spec.VERSION}
    new.update(_copy(data, "where", "from", "measure", "aggregation"))
    if data.get("best"):
        new["by"] = data["best"]
    new.update(_copy(data, "unit", "decimals", "ignore_period"))
    if data.get("compare"):
        good = data.get("good", "up")
        new["compare"] = True if good == "up" else {"good": good}
    if data.get("detail"):
        new["detail"] = {"measure": data["detail"]}
        if data.get("detail_label"):
            new["detail"]["label"] = data["detail_label"]
    if data.get("derive"):
        new["computed"] = dict(data["derive"])
    return new


def _upgrade_graph(data: dict) -> dict:
    x, y = data.get("x") or {}, data.get("y") or {}
    if x.get("aggregation", "none") != "none":
        raise ValueError("graph : an aggregation on x has no version 2 syntax")
    new = {"version": spec.VERSION, "type": data.get("graph_type", "bar")}
    new.update(_copy(data, "where", "from"))
    if "name" in x:
        new["by"] = x["name"]
    if data.get("monthly"):
        new["grain"] = "month"
    if "name" in y:
        new["measure"] = y["name"]
    new["aggregation"] = y.get("aggregation", "sum")
    if data.get("others"):
        new["others"] = True
    return new


def _upgrade_pivot(data: dict) -> dict:
    new = {"version": spec.VERSION}
    new.update(_copy(data, "from"))
    if "index" in data:
        new["rows"] = data["index"]
    if "column" in data:
        new["columns"] = data["column"]
    new.update(_copy(data, "measure", "aggregation"))
    if data.get("monthly"):
        new["grain"] = "month"
    return new


# ---- writing ----------------------------------------------------------------
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


def to_v2(text: str, kind: str) -> str | None:
    """A version 1 definition in version 2, as TOML ; None when it is not one."""
    data = serial.loads(text)
    if not is_legacy(data, kind):
        return None
    comments = dict(COMMENT_RE.findall(text))
    data = ordered(upgrade(data, kind), spec.KINDS[kind].entries)
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
        new = to_v2(unescape(definition.group(2)), kind.group(1))
        if new is None:
            return match.group(0)
        count += 1
        body = body[: definition.start(2)] + escape(new) + body[definition.end(2) :]
        return head + body + tail

    return RECORD_RE.sub(record, source), count


def migrate_db(db: str) -> int:
    """The tiles of `db` written in version 1, rewritten in version 2 ; how many."""
    from kpiten_core.backend import Backend

    backend = Backend.create(db=db)
    tiles = backend.call(
        backend.kpi_model,
        "search_read",
        domain=[("kind", "in", list(spec.KINDS))],
        fields=["name", "kind", "definition"],
    )
    count = 0
    for tile in tiles:
        new = to_v2(tile["definition"] or "", tile["kind"])
        if new is None:
            continue
        backend.call(
            backend.kpi_model, "write", ids=[tile["id"]], vals={"definition": new}
        )
        print(f"  {tile['kind']} {tile['name']!r}")
        count += 1
    return count


def main(args: list[str]) -> None:
    if args[:1] == ["--db"]:
        for db in args[1:]:
            print(f"{db} : {migrate_db(db)} tile(s) in version {spec.VERSION}")
        return
    for name in args:
        path = Path(name)
        content, count = migrate(path.read_text())
        if count:
            path.write_text(content)
        print(f"{path} : {count} definition(s) in version {spec.VERSION}")


if __name__ == "__main__":
    main(sys.argv[1:])
