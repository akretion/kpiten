"""See what a function of kpiten-core does, value by value, while tests run.

    .venv/bin/python scripts/eye.py kpiten_core.querychat.narrow_store \
        -- tests/test_querychat.py -k lines_follow
    .venv/bin/python -m birdseye          # then http://localhost:7777

The functions named before `--` are traced during the pytest run given after it, with
birdseye (`@eye` : every expression of every call, in a web page) or, with `--snoop`,
with snoop (each line run and the values that change, in the terminal). Nothing is
changed in the code : the functions are wrapped for this run only.

    .venv/bin/python scripts/eye.py --snoop kpiten_core.savetile.new_definition \
        -- tests/test_savetile.py

A name is a function of a module (`kpiten_core.querychat.links`) or a method of a class
(`kpiten_core.dfnorm.Df.get_df`). A function defined inside another one cannot be
named : trace the one around it. What birdseye records goes to `~/.birdseye.db`
(`BIRDSEYE_DB` to change it).

Worth it on the functions that compute (querychat, savetile, dfnorm, filters,
render.plotly) ; less on polars in lazy mode : a variable holds a plan, not rows.
"""

import importlib
import sys

import pytest


def resolve(name: str):
    """(owner, attribute, function) of a dotted name : the longest importable module,
    then the attributes (a class, a method)."""
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            owner = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attribute in parts[cut:-1]:
            owner = getattr(owner, attribute)
        return owner, parts[-1], getattr(owner, parts[-1])
    raise SystemExit(f"{name} : no module found")


def main(argv: list[str]) -> int:
    if "--" not in argv:
        raise SystemExit(__doc__)
    split = argv.index("--")
    names, pytest_args = argv[:split], argv[split + 1 :]
    use_snoop = "--snoop" in names
    names = [n for n in names if n != "--snoop"]
    if not names:
        raise SystemExit("name at least one function before --")
    if use_snoop:
        import snoop

        wrap = snoop.snoop()
        pytest_args = ["-s", *pytest_args]  # snoop writes to the terminal
    else:
        from birdseye import eye as wrap
    for name in names:
        owner, attribute, function = resolve(name)
        # a class attribute : keep a staticmethod / classmethod what it was
        raw = (
            owner.__dict__.get(attribute, function)
            if isinstance(owner, type)
            else function
        )
        if isinstance(raw, (staticmethod, classmethod)):
            setattr(owner, attribute, type(raw)(wrap(raw.__func__)))
        else:
            setattr(owner, attribute, wrap(function))
        print(f"traced : {name}")
    code = pytest.main(pytest_args)
    if not use_snoop:
        print("\nbirdseye : .venv/bin/python -m birdseye, then http://localhost:7777")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
