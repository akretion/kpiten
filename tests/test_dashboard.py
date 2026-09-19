"""End-to-end smoke tests of the Shiny dashboard, against the running stack.

Odoo (:8069) and Shiny (:5000) must be up (`make up`) with a demo database
(`big` by default), else the tests are skipped. A demo user (Marie) goes
through the SSO of Odoo, like a user does from the KpiTen menu.
"""

import os

import pytest
import requests
from playwright.sync_api import Page, expect

from shiny_kpiten import themes

ODOO = os.environ.get("E2E_ODOO_URL", "http://localhost:8069")
SHINY = os.environ.get("E2E_SHINY_URL", "http://localhost:5000")
DB = os.environ.get("E2E_DB", "big")
LOGIN = os.environ.get("E2E_LOGIN", "marie.stourne")
PASSWORD = os.environ.get("E2E_PASSWORD", "marie")
# a KpiTen manager (the admin of Odoo is one)
MANAGER = os.environ.get("E2E_MANAGER_LOGIN", "admin")
MANAGER_PASSWORD = os.environ.get("E2E_MANAGER_PASSWORD", "admin")

TILES = ".tile-grid .tile"
CARDS = ".card-grid .tile"
DELTAS = ".tile-grid .kpi-delta"


def _rpc(session: requests.Session, path: str, **params) -> dict:
    reply = session.post(
        ODOO + path,
        json={"jsonrpc": "2.0", "method": "call", "params": params},
        timeout=60,
    )
    return reply.json()


def sso_url(login: str = LOGIN, password: str = PASSWORD) -> str:
    """The URL Odoo gives to open the dashboard for `login` (skips without a stack)."""
    session = requests.Session()
    try:
        auth = _rpc(
            session,
            "/web/session/authenticate",
            db=DB,
            login=login,
            password=password,
        )
        if not auth.get("result", {}).get("uid"):
            pytest.skip(f"{login} cannot log in to {DB} on {ODOO}")
        reply = _rpc(
            session,
            "/web/dataset/call_kw/kt/action_redirect_to_kpiten",
            model="kt",
            method="action_redirect_to_kpiten",
            args=["shiny"],
            kwargs={},
        )
        requests.get(SHINY, timeout=10)
    except requests.ConnectionError:
        pytest.skip("Odoo and Shiny are not both running (make up)")
    return reply["result"]["url"]


def open_dashboard(page: Page, login: str = LOGIN, password: str = PASSWORD) -> None:
    page.goto(sso_url(login, password))
    page.locator(TILES).first.wait_for(timeout=90_000)


def test_sso_opens_the_dashboard(page: Page) -> None:
    open_dashboard(page)
    assert page.locator(TILES).count() > 0
    assert "Not connected" not in page.content()


def test_without_session_asks_to_log_in(page: Page) -> None:
    try:
        page.goto(f"{SHINY}/dashboard")
    except Exception:
        pytest.skip("Shiny is not running (make up)")
    page.get_by_text("Not connected").first.wait_for(timeout=30_000)
    assert page.locator(TILES).count() == 0


def test_edit_mode_is_for_kpiten_managers_only(page: Page) -> None:
    open_dashboard(page)  # Marie : reads, does not edit
    assert not page.locator("#edit_mode").is_visible()

    page.context.clear_cookies()
    open_dashboard(page, MANAGER, MANAGER_PASSWORD)
    page.locator("#edit_mode").wait_for(state="visible", timeout=30_000)


def test_comparison_switch_of_kt_config(page: Page) -> None:
    """The cards show their change since the previous period unless kt.config says no."""
    from kpiten_core.backend import Backend

    config = Backend.create(db=DB).env["kt.config"]
    ids = config.search([], limit=1)
    initial = config.read(ids, ["show_card_comparison"])[0]["show_card_comparison"]
    try:
        config.write(ids, {"show_card_comparison": True})
        open_dashboard(page)
        page.locator(DELTAS).first.wait_for(timeout=30_000)

        config.write(ids, {"show_card_comparison": False})
        open_dashboard(page)
        page.wait_for_load_state("networkidle")
        assert page.locator(CARDS).count() > 0  # the cards are drawn...
        assert page.locator(DELTAS).count() == 0  # ...without the comparison
    finally:  # the setting is left as it was found
        config.write(ids, {"show_card_comparison": initial})


def test_table_link_opens_the_odoo_record_in_a_new_tab(page: Page) -> None:
    """A link of a table opens the order in Odoo, in another tab : the user is logged in
    to Odoo in the same browser (that is where the SSO starts)."""
    try:
        page.goto(f"{ODOO}/web/login?db={DB}")
    except Exception:
        pytest.skip("Odoo is not running (make up)")
    page.fill("input[name=login]", LOGIN)
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url("**/odoo**", timeout=60_000)
    open_dashboard(page)
    link = page.locator(".tile .gt_table a[href*='/odoo/sale.order/']").first
    link.wait_for(timeout=60_000)
    with page.context.expect_page(timeout=20_000) as opened:
        link.click()
    record = opened.value
    record.wait_for_selector(".o_form_view", timeout=30_000)
    assert "/odoo/sale.order/" in record.url
    assert record.locator(".o_error_dialog").count() == 0


def test_drill_down_shows_the_rows_behind_a_table_row(page: Page) -> None:
    """A click on a row of Top Products opens the order lines of that product."""
    open_dashboard(page)
    tile = page.locator(".tile.drillable", has_text="Top Products").first
    tile.wait_for(timeout=60_000)
    tile.locator(".gt_table tbody tr").first.locator("td").nth(1).click()
    modal = page.locator(".modal-dialog")
    modal.locator(".gt_table").wait_for(timeout=30_000)
    columns = [c.strip() for c in modal.locator(".gt_table thead th").all_inner_texts()]
    assert columns == ["Date", "Order", "Customer", "Quantity", "Revenue"]
    assert modal.locator(".gt_table tbody tr").count() > 0


def test_drill_down_of_an_order_reads_another_table(page: Page) -> None:
    """Top Sales Orders : a click shows the lines of the order (the sale.order.line table)."""
    open_dashboard(page)
    tile = page.locator(".tile.drillable", has_text="Top Sales Orders").first
    tile.wait_for(timeout=60_000)
    tile.locator(".gt_table tbody tr").first.locator("td").nth(1).click()
    modal = page.locator(".modal-dialog")
    modal.locator(".gt_table").wait_for(timeout=30_000)
    columns = [c.strip() for c in modal.locator(".gt_table thead th").all_inner_texts()]
    assert columns == ["Product", "Quantity", "Unit price", "Subtotal"]


def test_explore_downloads_the_rows_of_the_user_with_a_notebook(
    page: Page, tmp_path
) -> None:
    """Explore : a zip of the parquets of the panel, with the rights of the user (Marie sees
    her own orders only) and the filters set, and a marimo notebook on them."""
    import io
    import json
    import zipfile

    import polars as pl

    open_dashboard(page)
    page.locator("#explore").wait_for(timeout=60_000)
    with page.expect_download(timeout=120_000) as download:
        page.locator("#explore").click()
    archive = zipfile.ZipFile(download.value.path())
    assert {"manifest.json", "explore.py", "README.txt", "sale.order.parquet"} <= set(
        archive.namelist()
    )
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["panel"] == "Sales" and manifest["filters"]
    orders = pl.read_parquet(io.BytesIO(archive.read("sale.order.parquet")))
    assert orders.height > 0
    assert set(orders["user_id"].drop_nulls().to_list()) <= {"Marie STOURNE"}
    assert "pl.scan_parquet" in archive.read("explore.py").decode()


def rgb(hex_color: str) -> str:
    """`#00dc82` as the browser writes a computed color."""
    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgb({red}, {green}, {blue})"


def wait_for_theme(page: Page, key: str) -> None:
    """The css of the theme is in the page : its accent is the one of the palette."""
    page.wait_for_function(
        "accent => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--accent').trim().toLowerCase() === accent",
        arg=themes.THEMES[key].palette["accent"].lower(),
        timeout=30_000,
    )


def check_theme_is_shown(page: Page, key: str) -> None:
    """The theme is applied to the page and to the tiles, and the dropdown shows it."""
    theme = themes.THEMES[key]
    wait_for_theme(page, key)
    expect(page.locator("#theme")).to_have_value(key)
    expect(page.locator("#theme option:checked")).to_have_text(theme.name)
    # the tiles are drawn with the palette : their title is in the accent color
    expect(page.locator(f"{TILES} h3").first).to_have_css(
        "color", rgb(theme.palette["accent"])
    )


@pytest.mark.parametrize("key", list(themes.THEMES))
def test_selecting_a_theme_applies_it_and_the_dropdown_shows_it(
    page: Page, key: str
) -> None:
    open_dashboard(page)
    page.locator("#theme").wait_for(state="visible", timeout=30_000)
    page.select_option("#theme", key)
    check_theme_is_shown(page, key)


def test_the_theme_is_kept_when_the_page_is_reloaded(page: Page) -> None:
    """The choice is remembered by the browser : after a reload the tiles are still
    drawn in it, and the dropdown still shows it (not the default theme)."""
    open_dashboard(page)
    other = next(key for key in themes.THEMES if key != themes.DEFAULT_THEME)
    page.locator("#theme").wait_for(state="visible", timeout=30_000)
    page.select_option("#theme", other)
    check_theme_is_shown(page, other)

    page.reload()
    page.locator(TILES).first.wait_for(timeout=90_000)
    check_theme_is_shown(page, other)
