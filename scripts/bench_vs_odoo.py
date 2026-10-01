"""The Odoo « Sales » dashboard against the KpiTen « Sales (Odoo) » panel : the time a
change of period takes, in a browser (headless Chromium), as a user sees it.

Each run opens the page anew (no cache of the previous run), on the last 7 days, then
measures the change to a wider period, until its data are there :

- Odoo : the RPCs of the spreadsheet (`/web/dataset/call_kw`) are all answered and
  none starts for 0.5 s (the canvas is drawn right after) ;
- KpiTen : Shiny is idle again (`shiny:idle`) and stays so for 0.5 s (the tiles are
  in the page).

Odoo has no « full range » in its list : its widest period is « Last 3 Years », and
the empty choice (« Select period... ») removes the filter. Both are measured.

Odoo (:8069) and Shiny (:5000) must be up (`./stack start`) and serve the base :

    .venv/bin/python scripts/bench_vs_odoo.py --db big
    .venv/bin/python scripts/bench_vs_odoo.py --db big --login marie.stourne --runs 5
"""

import argparse
import json
import statistics
import time

import requests
from playwright.sync_api import Page, sync_playwright

QUIET = 0.5  # s without activity : the page is done


# ---- Odoo -------------------------------------------------------------------
class RpcWatch:
    """The RPCs of a page : in flight, the time of the last one answered, and the
    answers of `sale.report` (to read the figures back)."""

    def __init__(self, page: Page):
        self.inflight = 0
        self.last = time.perf_counter()
        self.calls: list[tuple[str, float]] = []
        self._start: dict = {}
        page.on("request", self._request)
        page.on("requestfinished", self._finished)
        page.on("requestfailed", self._finished)

    @staticmethod
    def _rpc(request) -> bool:
        return "/web/dataset/call_kw" in request.url

    def _request(self, request):
        if self._rpc(request):
            self.inflight += 1
            self._start[request] = time.perf_counter()
            self.last = time.perf_counter()

    def _finished(self, request):
        if self._rpc(request):
            self.inflight -= 1
            self.last = time.perf_counter()
            method = request.url.split("/call_kw/")[-1]
            self.calls.append((method, self.last - self._start.pop(request, self.last)))

    def reset(self):
        self.calls = []

    def wait_idle(self, page: Page, timeout: float = 300) -> float:
        """Waits until no RPC is in flight for QUIET ; returns the time of the last."""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            page.wait_for_timeout(50)
            if not self.inflight and time.perf_counter() - self.last > QUIET:
                return self.last
        raise TimeoutError("Odoo : the RPCs never stopped")


def odoo_login(page: Page, url: str, db: str, login: str, password: str):
    page.goto(f"{url}/web/login?db={db}")
    page.fill("input[name=login]", login)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url("**/odoo**", timeout=60_000)


def odoo_run(page: Page, url: str, dashboard: int, period: str) -> dict:
    watch = RpcWatch(page)
    page.goto(f"{url}/odoo/dashboards?dashboard_id={dashboard}")
    select = page.locator("select.date_filter_values").first
    select.wait_for(timeout=120_000)
    watch.wait_idle(page)  # the dashboard on its default period
    select.select_option("last_week")
    watch.wait_idle(page)
    watch.reset()
    start = time.perf_counter()
    select.select_option(period)
    last = watch.wait_idle(page)
    return {
        "ms": (last - start) * 1000,
        "rpcs": len(watch.calls),
        "slowest": max((d for _, d in watch.calls), default=0) * 1000,
    }


# ---- KpiTen -----------------------------------------------------------------
# the tiles are one output (`tiles`) : the time its new html is in the page and drawn
# (two frames after `shiny:value`) ; Shiny waits a moment before it computes (its
# inputs are debounced), the time of its idle state alone ends too early
TILES_JS = """
() => {
  window.__ktTiles = 0;
  $(document).on("shiny:busy", () => { window.__ktBusy = true; });
  $(document).on("shiny:idle", () => { window.__ktBusy = false; });
  $(document).on("shiny:value", (e) => {
    if (e.name !== "tiles") { return; }
    requestAnimationFrame(() => requestAnimationFrame(() => {
      window.__ktTiles = performance.now();
    }));
  });
}
"""
SETTLE = 1.5  # s without a new drawing of the tiles : the page is done


def tiles_drawn(page: Page, after: float, timeout: float = 300) -> float:
    """Waits for the tiles drawn after `after` (ms, the clock of the page), then for
    no other drawing for SETTLE ; returns the time of the last one (ms)."""
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        page.wait_for_timeout(50)
        busy, drawn, now = page.evaluate(
            "() => [!!window.__ktBusy, window.__ktTiles, performance.now()]"
        )
        if drawn > after and not busy and now - drawn > SETTLE * 1000:
            return drawn
    raise TimeoutError("KpiTen : the tiles were never drawn")


def sso_url(odoo: str, shiny: str, db: str, login: str, password: str) -> str:
    """The URL Odoo gives to open KpiTen (its SSO), as from the KpiTen menu."""
    session = requests.Session()

    def rpc(path, **params):
        reply = session.post(
            odoo + path,
            json={"jsonrpc": "2.0", "method": "call", "params": params},
            timeout=60,
        ).json()
        if "error" in reply:
            raise SystemExit(f"{path} : {reply['error']['data']['message']}")
        return reply["result"]

    rpc("/web/session/authenticate", db=db, login=login, password=password)
    action = rpc(
        "/web/dataset/call_kw/kt/action_redirect_to_kpiten",
        model="kt",
        method="action_redirect_to_kpiten",
        args=["shiny"],
        kwargs={},
    )
    return action["url"]


def kpiten_run(page: Page, url: str, panel: str, period: str) -> dict:
    page.goto(url)
    page.locator("select#panel").wait_for(timeout=120_000)
    page.evaluate(TILES_JS)
    now = lambda: page.evaluate("() => performance.now()")
    page.locator(".tile").first.wait_for(timeout=120_000)  # the first panel
    tiles_drawn(page, 0)
    for select, value in (("panel", panel), ("date_period", "last 7 days")):
        before = now()
        if select == "panel":
            page.select_option("select#panel", label=value)
        else:
            page.select_option(f"select#{select}", value)
        tiles_drawn(page, before)
    start = now()
    page.select_option("select#date_period", period)
    last = tiles_drawn(page, start)
    tiles = page.locator(".card-grid .tile, .tile-grid .tile").count()
    return {"ms": last - start, "tiles": tiles}


# ---- main -------------------------------------------------------------------
def summary(name: str, runs: list[dict]):
    times = [r["ms"] for r in runs]
    extra = {k: v for k, v in runs[-1].items() if k != "ms"}
    print(
        f"{name:<42} median {statistics.median(times):>7.0f} ms   "
        f"runs {' '.join(f'{t:.0f}' for t in times)}   {json.dumps(extra)}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default="big")
    parser.add_argument("--login", default="admin")
    parser.add_argument("--password", help="default : the login before its dot")
    parser.add_argument("--odoo", default="http://localhost:8069")
    parser.add_argument("--shiny", default="http://localhost:5000")
    parser.add_argument("--dashboard", type=int, default=3, help="the Odoo dashboard")
    parser.add_argument("--panel", default="Sales (Odoo)", help="the KpiTen panel")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    password = args.password or args.login.split(".")[0]

    print(f"{args.db}, {args.login} : last 7 days → a wider period, {args.runs} runs")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        odoo_login(page, args.odoo, args.db, args.login, password)
        for period, label in (("last_three_years", "Last 3 Years"), ("", "no period")):
            runs = []
            for _ in range(args.runs):
                page = context.new_page()
                runs.append(odoo_run(page, args.odoo, args.dashboard, period))
                page.close()
            summary(f"Odoo, {label}", runs)

        runs = []
        for _ in range(args.runs):
            page = context.new_page()
            url = sso_url(args.odoo, args.shiny, args.db, args.login, password)
            runs.append(kpiten_run(page, url, args.panel, ""))
            page.close()
        summary("KpiTen, full range", runs)
        browser.close()


if __name__ == "__main__":
    main()
