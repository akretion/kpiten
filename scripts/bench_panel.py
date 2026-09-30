"""The time of the panels of a database, computed as the Shiny dashboard does
(`panel_results`) : the store of a user (ACL, record rules), the default period
of the panel, then `exec_tile` for each tile. Needs the Odoo of the stack.

    .venv/bin/python scripts/bench_panel.py --db big
    .venv/bin/python scripts/bench_panel.py --db big --login marie.stourne
    .venv/bin/python scripts/bench_panel.py --db big --workers 4 --runs 3

Prints the time of the user store, then of each tile and of each panel.
"""

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from kpiten_core import env, filters, labels, loaders
from kpiten_core import tiles as core_tiles
from kpiten_core.backend import Backend


def ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def user_id_of(backend, login: str | None) -> int:
    if not login:
        return backend.current_user_id()
    users = backend.call(
        "res.users", "search_read", domain=[("login", "=", login)], fields=["id"]
    )
    if not users:
        raise SystemExit(f"no user {login}")
    return users[0]["id"]


def panel_predicates(store: dict, settings: dict):
    """The predicates of the panel as it opens : its default period, no dimension."""
    config = settings.get("filter_config") or {}
    date_value = None
    if config.get("date"):
        options = filters.date_options(filters.date_range(store, config))
        date_value = filters.bounds_of_option(
            filters.default_date_option(options, filters.date_range(store, config))
        )
    return (
        filters.make_predicates(config, date_value, {}),
        filters.make_previous_predicates(config, date_value, {}),
        filters.describe_previous(date_value),
    )


def run_tile(line, store, predicates, previous, previous_label, field_labels):
    start = time.perf_counter()
    try:
        core_tiles.exec_tile(
            line,
            line["model"],
            store,
            predicates,
            previous,
            previous_label,
            field_labels,
        )
        error = None
    except Exception as err:
        error = str(err)[:60]
    return ms(start), error


def bench_panel(backend, uid, panel, store, field_labels, workers, runs, verbose):
    settings = backend.get_panel_settings(panel["id"])
    lines = backend.get_panel_tiles(panel["id"], uid)
    predicates, previous, previous_label = panel_predicates(store, settings)
    args = (store, predicates, previous, previous_label, field_labels)
    totals = []
    per_tile: dict[int, list[float]] = {}
    errors: dict[int, str] = {}
    for _run in range(runs):
        start = time.perf_counter()
        if workers > 1:
            with ThreadPoolExecutor(workers) as pool:
                results = list(pool.map(lambda line: run_tile(line, *args), lines))
        else:
            results = [run_tile(line, *args) for line in lines]
        totals.append(ms(start))
        for line, (took, error) in zip(lines, results):
            per_tile.setdefault(line["id"], []).append(took)
            if error:
                errors[line["id"]] = error
    # the first run opens the tables the panel reads (their record rules)
    print(
        f"panel {panel['name']!r} : {len(lines)} tiles, first {totals[0]:.0f} ms, "
        f"then {statistics.median(totals[1:] or totals):.0f} ms (median of {runs})"
    )
    if verbose:
        for line in lines:
            took = statistics.median(per_tile[line["id"]])
            note = f"  ERROR {errors[line['id']]}" if line["id"] in errors else ""
            print(
                f"    {took:7.0f} ms  {line['kind']:9s} {line['model']:22s} "
                f"{line['name']}{note}"
            )
    return statistics.median(totals)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="big")
    parser.add_argument("--login", help="the user (default : the rpc login)")
    parser.add_argument("--panel", help="the panels whose name has it")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("-q", "--quiet", action="store_true", help="no tile times")
    args = parser.parse_args()

    backend = Backend.create(db=args.db)
    env.current_db = backend.db
    uid = user_id_of(backend, args.login)
    lang = backend.get_user_lang(uid)
    field_labels = labels.field_labels_of(backend, lang)

    start = time.perf_counter()
    store = loaders.tile_store(backend, uid)
    print(f"user store ({args.login or 'rpc user'}) : {ms(start):.0f} ms")

    total = 0.0
    with env.db_scope(backend.db):
        for panel in backend.get_panels():
            if args.panel and args.panel.lower() not in panel["name"].lower():
                continue
            total += bench_panel(
                backend,
                uid,
                panel,
                store,
                field_labels,
                args.workers,
                args.runs,
                not args.quiet,
            )
    print(f"all panels : {total:.0f} ms (workers={args.workers})")


if __name__ == "__main__":
    main()
