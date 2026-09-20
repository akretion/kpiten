#!/usr/bin/env python3
"""Downgrade the views of the modules of this repo, written for Odoo 18, to an older series.

    python3 scripts/downgrade.py 16.0 [PATH]

The XML of the modules (the `data` and `demo` files of the manifests) is rewritten in
place, the `18.0` of the manifest versions becomes the target series. Only the standard
library is needed. It is meant to be played by git-aggregator (`repos.yml`), on the
branch it just built :

    shell_command_after:
      - python3 scripts/downgrade.py 16.0
      - git add . && git commit -m "downgrade to 16.0"

What is converted (the Python side is in `kpiten/compat.py`) :

    < 18   <list> -> <tree>, view_mode `list` -> `tree`,
           <t t-name="card"> -> <t t-name="kanban-box"> wrapped in a clickable <div>,
           a numbercall of -1 on the crons (Odoo 18 has no numbercall, older ones run
           the cron once by default)
    < 17   invisible / readonly / required / column_invisible = "expression" ->
           attrs="{'invisible': [domain]}"

An expression that can't be turned into a domain (a call, `parent.x`, ...) stops the
conversion with the file and line, so that nothing is silently wrong.
"""

import argparse
import ast
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import quoteattr

LATEST = 18
OLDEST = 14
MODIFIERS = ("invisible", "readonly", "required", "column_invisible")
STATIC_TRUE = {"1", "True", "true"}
STATIC_FALSE = {"0", "False", "false"}
# the keywords an expression may use and be left as it is (evaluated by the client)
CLIENT_NAMES = {"context"}

SKIPPED = re.compile(r"(<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>)", re.S)
TOKEN = re.compile(
    r"""<(?P<name>[A-Za-z_][\w.:-]*)
        (?P<attrs>(?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*)
        (?P<space>\s*)(?P<end>/?)>
        |</(?P<close>[\w.:-]+)\s*>""",
    re.X,
)
ATTR = re.compile(
    r"""(?P<all>\s+(?P<key>[^\s=/>]+)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'))"""
)
CRON = re.compile(
    r"(<record\b[^>]*model=\"ir\.cron\"[^>]*>)(.*?)(\s*)(</record>)", re.S
)
VIEW_MODE = re.compile(r"(<field\s+name=\"view_mode\"[^>]*>)([^<]*)(</field>)")
INVERSE = {
    "=": "!=",
    "!=": "=",
    "<": ">=",
    ">": "<=",
    "<=": ">",
    ">=": "<",
    "in": "not in",
    "not in": "in",
}
COMPARE = {
    ast.Eq: "=",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.Gt: ">",
    ast.LtE: "<=",
    ast.GtE: ">=",
    ast.In: "in",
    ast.NotIn: "not in",
}
FLIPPED = {"=": "=", "!=": "!=", "<": ">", ">": "<", "<=": ">=", ">=": "<="}


class ConversionError(Exception):
    pass


# ---- expression -> domain -------------------------------------------------------


def leaf(node):
    """`field`, or `field op constant`, as a domain leaf."""
    if isinstance(node, ast.Name):
        return (node.id, "!=", False)
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
        raise ValueError("unsupported expression")
    op = COMPARE.get(type(node.ops[0]))
    left, right = node.left, node.comparators[0]
    if op and isinstance(left, ast.Name):
        return (left.id, op, ast.literal_eval(right))
    if op in FLIPPED and isinstance(right, ast.Name):  # 'a' == field
        return (right.id, FLIPPED[op], ast.literal_eval(left))
    raise ValueError("unsupported comparison")


def tree(node, negate=False):
    """The expression as ("and" | "or", [children]) of domain leaves ; `negate` pushes a
    `not` down to the leaves."""
    if isinstance(node, ast.BoolOp):
        kind = "and" if isinstance(node.op, ast.And) else "or"
        if negate:
            kind = "or" if kind == "and" else "and"
        return (kind, [tree(value, negate) for value in node.values])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return tree(node.operand, not negate)
    name, op, value = leaf(node)
    return (name, INVERSE[op] if negate else op, value)


def prefix(node, top=False):
    """The domain, in prefix notation (the top level `and` is the implicit one)."""
    if isinstance(node, tuple) and len(node) == 3 and isinstance(node[0], str):
        return [node]
    kind, children = node
    terms = [term for child in children for term in prefix(child)]
    if kind == "and" and top:
        return terms
    return ["&" if kind == "and" else "|"] * (len(children) - 1) + terms


def to_domain(expression):
    parsed = ast.parse(html.unescape(expression).strip(), mode="eval").body
    return prefix(tree(parsed), top=True)


def names(expression):
    parsed = ast.parse(html.unescape(expression).strip(), mode="eval")
    return {n.id for n in ast.walk(parsed) if isinstance(n, ast.Name)}


# ---- one tag --------------------------------------------------------------------


def convert_attrs(name, attrs, series, where):
    """The attributes of a tag for the series : (attrs, wrap) where wrap tells that the
    tag is a kanban card template, that needs a wrapper."""
    wrap = False
    if series < 18 and name == "t" and re.search(r'\st-name="card"', attrs):
        attrs = attrs.replace('t-name="card"', 't-name="kanban-box"')
        wrap = True
    if series >= 17:
        return attrs, wrap
    modifiers = {}
    for found in list(ATTR.finditer(attrs)):
        key = found["key"]
        if key not in MODIFIERS:
            continue
        value = found["dq"] if found["dq"] is not None else found["sq"]
        text = html.unescape(value).strip()
        if text in STATIC_TRUE:
            if key == "column_invisible":  # a column is hidden by `invisible` in a list
                attrs = attrs.replace(
                    found["all"], found["all"].replace(key, "invisible")
                )
            continue
        attrs = attrs.replace(found["all"], "")
        if text in STATIC_FALSE:
            continue
        if names(text) <= CLIENT_NAMES and key != "column_invisible":
            attrs += found["all"]  # `context` only : evaluated by the client as it is
            continue
        try:
            modifiers[key] = to_domain(text)
        except (ValueError, SyntaxError, KeyError) as error:
            raise ConversionError(
                f'{where} : <{name} {key}="{text}"> can\'t be a domain ({error})'
            )
    if modifiers:
        attrs += " attrs=" + quoteattr(repr(modifiers))
    return attrs, wrap


def convert_views(text, series, path):
    """The tags of the XML `text`, comments and CDATA left alone."""
    pieces, stack, offset = [], [], 0

    def where(position):
        return f"{path}:{text.count(chr(10), 0, position) + 1}"

    def replace(base):
        def convert(m):
            if m["close"]:
                name, wrap = stack.pop() if stack else (m["close"], False)
                if wrap:
                    return "</div></t>"
                return f"</{'tree' if series < 18 and name == 'list' else name}>"
            name = m["name"]
            if series < 18 and name == "chatter":
                raise ConversionError(
                    f"{where(base + m.start())} : <chatter> has no equivalent"
                )
            attrs, wrap = convert_attrs(
                name, m["attrs"], series, where(base + m.start())
            )
            if not m["end"]:
                stack.append((name, wrap))
            new = "tree" if series < 18 and name == "list" else name
            tag = f"<{new}{attrs}{m['space']}{m['end']}>"
            return tag + '<div class="oe_kanban_global_click">' if wrap else tag

        return convert

    for index, chunk in enumerate(SKIPPED.split(text)):
        # the odd chunks are what SKIPPED matched : comments, CDATA, declarations
        pieces.append(chunk if index % 2 else TOKEN.sub(replace(offset), chunk))
        offset += len(chunk)
    return "".join(pieces)


# ---- the records ----------------------------------------------------------------


def convert_records(text, series):
    if series >= 18:
        return text

    def view_mode(m):
        modes = [
            ("tree" if mode.strip() == "list" else mode) for mode in m[2].split(",")
        ]
        return m[1] + ",".join(modes) + m[3]

    def cron(m):
        if "numbercall" in m[2]:
            return m[0]
        indent = re.findall(r"\n([ \t]*)<field", m[2])
        indent = indent[-1] if indent else "    "
        field = f'\n{indent}<field name="numbercall">-1</field>'
        return m[1] + m[2] + field + m[3] + m[4]

    return CRON.sub(cron, VIEW_MODE.sub(view_mode, text))


def convert_xml(text, series, path):
    return convert_records(convert_views(text, series, path), series)


# ---- the repo -------------------------------------------------------------------


def convert_module(module, series):
    """Converts the module dir, returns the files changed."""
    manifest = module / "__manifest__.py"
    data = ast.literal_eval(manifest.read_text())
    changed = []
    version = re.sub(
        r"([\"']version[\"']\s*:\s*[\"'])18\.0(?=\.)",
        rf"\g<1>{series}.0",
        manifest.read_text(),
    )
    if version != manifest.read_text():
        manifest.write_text(version)
        changed.append(manifest)
    for name in data.get("data", []) + data.get("demo", []):
        path = module / name
        if path.suffix != ".xml":
            continue
        old = path.read_text()
        new = convert_xml(old, series, path)
        if new != old:
            try:
                ET.fromstring(new.encode())
            except ET.ParseError as error:
                raise ConversionError(f"{path} : the result is not XML ({error})")
            path.write_text(new)
            changed.append(path)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("series", help="target series, ex. 16.0")
    parser.add_argument("path", nargs="?", default=".", help="the repo (default : .)")
    args = parser.parse_args(argv)
    series = int(args.series.split(".")[0])
    if not OLDEST <= series < LATEST or not args.series.endswith(".0"):
        sys.exit(
            f"series {OLDEST}.0 to {LATEST - 1}.0 (views are written for {LATEST}.0)"
        )
    modules = sorted(m.parent for m in Path(args.path).glob("*/__manifest__.py"))
    try:
        for module in modules:
            for path in convert_module(module, series):
                print("converted", path)
    except ConversionError as error:
        sys.exit(f"downgrade to {args.series} failed : {error}")
    print(f"{len(modules)} module(s) for Odoo {args.series}")


if __name__ == "__main__":
    main()
