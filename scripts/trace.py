"""The calls of kpiten-core on a timeline (VizTracer) : who calls whom, how long,
in which thread, with the arguments and the return values.

    .venv/bin/python scripts/trace.py tiles                 # every demo tile
    .venv/bin/python scripts/trace.py tiles -k "Top"        # the tiles whose name has it
    .venv/bin/python scripts/trace.py panel                 # a panel filter that spreads
    .venv/bin/vizviewer trace.json                          # then the page it opens

It runs on the real sample of `tests/data` (the rows of the demo models and the tiles of
their datasets, `make sample-fixtures`) : no Odoo. Only the code of `kpiten_core` is
recorded (the calls into polars are left out), so the timeline stays readable.

Where `scripts/eye.py` shows the values inside one function, this shows the path
through the core : `exec_tile` -> `card_value` -> `filter_df` -> `derive_columns`...
(The file filter of VizTracer keeps a call only when the whole chain that leads to it
is included : under pytest, nothing. Hence a script.)
"""

import argparse
import json
import pathlib

import polars as pl
from viztracer import VizTracer

import kpiten_core
from kpiten_core import querychat, tiles

DATA = pathlib.Path(__file__).parents[1] / "tests" / "data"
MODELS = ["sale.order", "sale.order.line", "purchase.order", "purchase.order.line"]


def sample_store() -> dict:
    return {m: pl.read_parquet(DATA / f"{m}.parquet").lazy() for m in MODELS}


def run_tiles(store: dict, pattern: str | None) -> None:
    """Each demo tile, as a front computes it (no period : the whole sample)."""
    for tile in json.loads((DATA / "tiles.json").read_text()):
        if pattern and pattern.lower() not in tile["name"].lower():
            continue
        line = {
            "kind": tile["kind"],
            "name": tile["name"],
            "content": tile["definition"],
            "drill": tile["drill"],
        }
        try:
            tiles.exec_tile(line, tile["model"], store, [])
            print(f"traced : {tile['name']} ({tile['kind']})")
        except Exception as err:  # a tile of the sample may miss its data
            print(f"failed : {tile['name']} : {err}")


def run_panel(store: dict) -> None:
    """A filter of the AI on the orders of a panel : their lines follow (querychat)."""
    rels = {"sale.order": {}, "sale.order.line": {"order_id": "sale.order"}}
    narrowed, followed = querychat.narrow_store(
        store, {"sale.order": "amount_untaxed > 2000"}, rels, list(rels)
    )
    rows = narrowed["sale.order.line"].select(pl.len()).collect().item()
    print(f"traced : narrow_store, followed {followed}, {rows} lines kept")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("tiles", "panel"))
    parser.add_argument("-k", help="tiles : only those whose name has this text")
    parser.add_argument("-o", default="trace.json", help="the file of the trace")
    args = parser.parse_args()
    store = sample_store()  # read before the trace : the timeline starts at the work
    tracer = VizTracer(
        # a call is kept when the whole chain that leads to it is included : this
        # script too (and why the filter records nothing under pytest)
        include_files=[str(pathlib.Path(kpiten_core.__file__).parent), __file__],
        log_func_args=True,
        log_func_retval=True,
        ignore_c_function=True,  # isinstance, dict.get... : noise
        output_file=args.o,
        verbose=0,
    )
    tracer.start()
    run_tiles(store, args.k) if args.what == "tiles" else run_panel(store)
    tracer.stop()
    tracer.save()
    print(f"\n{args.o} : .venv/bin/vizviewer {args.o}")


if __name__ == "__main__":
    main()
