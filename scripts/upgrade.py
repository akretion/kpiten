#!/usr/bin/env python3
"""Upgrade the modules of this repo, written for Odoo 18, to a newer series.

    python3 scripts/upgrade.py 20.0 [PATH]

The symmetric of `downgrade.py` : the data files of the modules are rewritten in
place, the `18.0` of the manifest versions becomes the target series. Only the
standard library is needed. It is meant to be played by git-aggregator
(`repos.yml`), on the branch it just built :

    shell_command_after:
      - python3 scripts/upgrade.py 20.0
      - git add . && git commit -m "upgrade to 20.0"

What is converted (the Python side is in `kpiten/compat.py`) :

    >= 20  security/ir.model.access.csv -> security/ir.access.csv : `ir.model.access`
           and `ir.rule` are one model, `ir.access` (a model name, an operation
           `crud`, a domain) ; a line granting nothing is dropped

The Python side, what is written to run on every series :

    `models.Constraint` (19+) or `_sql_constraints`   compat.sql_constraints
    `get_str` / `set_str` (20) or `get_param` / ...   compat.get_param, set_param
    `group_ids` (19+) or `groups_id` on res.users      compat.groups_field
    the French chart `fr_comp` (20) or `fr`            erp_commercial_data
    no `done` purchase state (a locked one), no stored
    `state` on the lines, no `invoiced_target`, no
    « All » product category (20)                      erp_commercial_data

and in the XML of every series : a search view `<group>` without `expand` / `string`.

The rules come from installing the modules on the newer series and reading its
errors and warnings : a new series may need new ones.
"""

import argparse
import ast
import csv
import io
import re
import sys
from pathlib import Path

LATEST = 20
SOURCE = 18
# the letters of an `ir.access` operation, in the order Odoo writes them
OPERATIONS = (
    ("c", "perm_create"),
    ("r", "perm_read"),
    ("u", "perm_write"),
    ("d", "perm_unlink"),
)
MODEL_NAME = re.compile(r"""^\s*_name\s*=\s*["']([\w.]+)["']""", re.M)


class ConversionError(Exception):
    pass


def model_names(module):
    """The `model_<name>` xml ids of the models this module declares, and their
    names (`model_kt_kpi` -> `kt.kpi`)."""
    names = {}
    for path in module.rglob("*.py"):
        for name in MODEL_NAME.findall(path.read_text()):
            names["model_" + name.replace(".", "_")] = name
    return names


def model_of(ref, module, names, path):
    """The model name of an `ir.model` xml id of the access file."""
    owner, _, xmlid = ref.rpartition(".")
    if owner and owner != module.name:
        raise ConversionError(f"{path} : {ref} is a model of another module")
    if xmlid not in names:
        raise ConversionError(f"{path} : no model declares {ref}")
    return names[xmlid]


def convert_access(text, module, path):
    """`ir.model.access` csv -> `ir.access` csv."""
    names = model_names(module)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", "name", "model_id", "group_id/id", "operation", "domain"])
    for row in csv.DictReader(io.StringIO(text)):
        operation = "".join(
            letter for letter, perm in OPERATIONS if row[perm].strip() == "1"
        )
        if not operation:
            continue  # grants nothing
        model = model_of(row["model_id:id"], module, names, path)
        writer.writerow(
            [row["id"], row["name"], model, row["group_id:id"], operation, ""]
        )
    return out.getvalue()


# ---- the repo -------------------------------------------------------------------


def convert_module(module, series):
    """Converts the module dir, returns the files changed."""
    manifest = module / "__manifest__.py"
    text = manifest.read_text()
    changed = []
    new = re.sub(
        rf"([\"']version[\"']\s*:\s*[\"']){SOURCE}\.0(?=\.)",
        rf"\g<1>{series}.0",
        text,
    )
    access = module / "security" / "ir.model.access.csv"
    if series >= 20 and access.exists():
        target = access.with_name("ir.access.csv")
        target.write_text(convert_access(access.read_text(), module, access))
        access.unlink()
        new = new.replace("security/ir.model.access.csv", "security/ir.access.csv")
        changed.append(target)
    if new != text:
        ast.literal_eval(new)  # still a manifest
        manifest.write_text(new)
        changed.append(manifest)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("series", help="target series, ex. 20.0")
    parser.add_argument("path", nargs="?", default=".", help="the repo (default : .)")
    args = parser.parse_args(argv)
    series = int(args.series.split(".")[0])
    if not SOURCE < series <= LATEST or not args.series.endswith(".0"):
        sys.exit(
            f"series {SOURCE + 1}.0 to {LATEST}.0 (the modules are written for "
            f"{SOURCE}.0)"
        )
    modules = sorted(m.parent for m in Path(args.path).glob("*/__manifest__.py"))
    try:
        for module in modules:
            for path in convert_module(module, series):
                print("converted", path)
    except ConversionError as error:
        sys.exit(f"upgrade to {args.series} failed : {error}")
    print(f"{len(modules)} module(s) for Odoo {args.series}")


if __name__ == "__main__":
    main()
