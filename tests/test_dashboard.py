"""End-to-end smoke tests of the Shiny dashboard, against the running stack.

Odoo (:8069) and Shiny (:5000) must be up (`make up`) with a demo database
(`big` by default), else the tests are skipped. A demo user (Marie) goes
through the SSO of Odoo, like a user does from the KpiTen menu.
"""

import contextlib
import os
import re
from urllib.parse import urljoin

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
    page.get_by_role("heading", name="Not connected").wait_for(timeout=30_000)
    assert page.locator(TILES).count() == 0
    expect(page).to_have_title("Not connected · KpiTen (shiny)")


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


def test_the_tab_title_names_the_open_panel(page: Page) -> None:
    """`Sales · KpiTen (shiny)` : the tab says which panel is open, and follows it."""
    open_dashboard(page)
    panel = page.locator("#panel")
    name = panel.locator("option:checked").inner_text()
    expect(page).to_have_title(f"{name} · KpiTen (shiny)")

    others = panel.locator("option:not(:checked)")
    if not others.count():
        pytest.skip("the user reads a single panel")
    other = others.first.inner_text()
    page.select_option("#panel", label=other)
    expect(page).to_have_title(f"{other} · KpiTen (shiny)")


def test_the_tab_has_a_favicon(page: Page) -> None:
    """The icon of the tab is served (the browser asked /favicon.ico : a 404)."""
    open_dashboard(page)
    href = page.locator("link[rel='icon']").get_attribute("href")
    reply = page.request.get(urljoin(page.url, href))
    assert reply.ok
    assert reply.headers["content-type"].startswith("image/")


@contextlib.contextmanager
def kt_config(**values):
    """Set fields of kt.config for a test, and put them back as they were found."""
    from kpiten_core.backend import Backend

    config = Backend.create(db=DB).env["kt.config"]
    ids = config.search([], limit=1)
    initial = config.read(ids, list(values))[0]
    initial.pop("id", None)
    try:
        config.write(ids, values)
        yield
    finally:
        config.write(ids, initial)


def test_the_default_theme_of_kt_config(page: Page) -> None:
    """A user who chose nothing gets the theme of the configuration, in the page and
    in the dropdown."""
    with kt_config(default_theme="midnight"):
        open_dashboard(page)
        page.locator("#theme").wait_for(state="visible", timeout=30_000)
        check_theme_is_shown(page, "midnight")


def test_the_rows_of_a_table_follow_kt_config(page: Page) -> None:
    with kt_config(table_rows=5):
        open_dashboard(page)
        rows = page.locator(".tile-grid .tile .gt_table").evaluate_all(
            "tables => tables.map(t => t.querySelectorAll('tbody tr').length)"
        )
        assert rows and max(rows) <= 5
        page.get_by_text(re.compile(r"First 5 of")).first.wait_for(timeout=30_000)


def test_the_number_format_of_kt_config(page: Page) -> None:
    """`1,234.56` : a comma between thousands, not the narrow space of the default."""
    with kt_config(number_format="comma_dot"):
        open_dashboard(page)
        values = " ".join(page.locator(f"{CARDS} .value").all_inner_texts())
        assert re.search(r"\d,\d{3}", values) and "\u202f" not in values
    with kt_config(number_format=False):
        open_dashboard(page)
        values = " ".join(page.locator(f"{CARDS} .value").all_inner_texts())
        assert "\u202f" in values  # the default : a narrow no-break space


def test_the_card_colors_of_kt_config(page: Page) -> None:
    """The change of a card is drawn in the good / bad color of the configuration."""
    with kt_config(
        show_card_comparison=True, card_good_color="#123456", card_bad_color="#654321"
    ):
        open_dashboard(page)
        page.locator(DELTAS).first.wait_for(timeout=30_000)
        colors = set(
            page.locator(DELTAS).evaluate_all(
                "els => els.map(e => getComputedStyle(e).color)"
            )
        )
        assert colors <= {"rgb(18, 52, 86)", "rgb(101, 67, 33)"} and colors


def test_who_may_export_follows_kt_config(page: Page) -> None:
    def has_button(login, password):
        page.context.clear_cookies()
        open_dashboard(page, login, password)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        return page.locator("#explore").count() > 0

    with kt_config(explore_access="nobody"):
        assert not has_button(LOGIN, PASSWORD)
        assert not has_button(MANAGER, MANAGER_PASSWORD)
    with kt_config(explore_access="managers"):
        assert not has_button(LOGIN, PASSWORD)  # Marie is not a manager
        assert has_button(MANAGER, MANAGER_PASSWORD)
    with kt_config(explore_access="everyone"):
        assert has_button(LOGIN, PASSWORD)


def login_to_odoo(page: Page, login: str = LOGIN, password: str = PASSWORD) -> None:
    """Logged in to Odoo in this browser, as when a user starts from the KpiTen menu."""
    try:
        page.goto(f"{ODOO}/web/login?db={DB}")
    except Exception:
        pytest.skip("Odoo is not running (make up)")
    page.fill("input[name=login]", login)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url("**/odoo**", timeout=60_000)


def test_a_kpi_that_lists_records_opens_the_same_list_in_odoo(page: Page) -> None:
    """The link under « Top Sales Orders » opens, in Odoo, the orders the tile lists :
    the ids of its rows are in the address, and Odoo shows those records."""
    with kt_config(feature_open_in_odoo=True):
        login_to_odoo(page)
        open_dashboard(page)
        tile = page.locator(".tile", has=page.locator(".records-link")).first
        tile.wait_for(timeout=60_000)
        listed = {
            int(found)
            for href in tile.locator("a[href*='/odoo/sale.order/']").evaluate_all(
                "els => els.map(e => e.href)"
            )
            for found in re.findall(r"/sale\.order/(\d+)", href)
        }
        assert listed  # the rows of the tile are orders
        link = tile.locator(".records-link")
        ids = re.search(r"active_ids=([\d,]+)", link.get_attribute("href"))[1]
        assert {int(i) for i in ids.split(",")} == listed  # the same records
        with page.context.expect_page(timeout=20_000) as opened:
            link.click()
        odoo = opened.value
        odoo.wait_for_selector(".o_list_view", timeout=60_000)
        odoo.wait_for_selector(".o_data_row", timeout=30_000)
        assert odoo.locator(".o_data_row").count() == len(listed)
        assert odoo.locator(".o_error_dialog").count() == 0


def test_the_link_is_not_there_when_the_feature_is_off(page: Page) -> None:
    with kt_config(feature_open_in_odoo=False):
        open_dashboard(page)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        assert page.locator(".records-link").count() == 0


def test_the_kpiten_logo_is_in_the_header_with_its_slogan_on_hover(page: Page) -> None:
    open_dashboard(page)
    logo = page.locator("img.kpiten-logo")
    expect(logo).to_have_attribute("title", "Le capitaine de vos KPI")
    reply = page.request.get(urljoin(page.url, logo.get_attribute("src")))
    assert reply.ok and reply.headers["content-type"].startswith("image/")


def test_the_logo_with_its_name_ends_the_page_on_the_right(page: Page) -> None:
    open_dashboard(page)
    page.wait_for_load_state("networkidle")
    footer = page.locator(".app-footer svg")
    footer.scroll_into_view_if_needed()
    box, last_tile = footer.bounding_box(), page.locator(TILES).last.bounding_box()
    assert box["x"] + box["width"] > page.viewport_size["width"] * 0.85  # on the right
    assert box["y"] >= last_tile["y"] + last_tile["height"]  # after every tile
    assert footer.get_attribute("aria-label") == "KpiTen, le capitaine de vos KPI"
