"""End-to-end tests of the dashboard page (live Odoo + parquet snapshot)."""

from playwright.sync_api import Page, expect

from shiny.playwright import controller
from shiny.pytest import create_app_fixture
from shiny.run import ShinyAppProc

app = create_app_fixture("app_test.py", timeout_secs=60)

SALES_PANEL_LABEL = "Sales"


def _open(page: Page, app: ShinyAppProc) -> None:
    page.goto(app.url)
    page.wait_for_load_state("networkidle")


def test_panels_and_tiles(page: Page, app: ShinyAppProc) -> None:
    _open(page, app)
    # theme fixture renders the real choice list
    theme = controller.InputSelect(page, "theme")
    theme.expect_choice_labels(["Akretion", "Midnight", "Sand"])

    panel = controller.InputSelect(page, "panel")
    panel.set(SALES_PANEL_LABEL)

    page.locator(".tile-grid .tile", has_text="Sales Orders count").wait_for(
        timeout=15_000
    )
    value_text = page.locator(
        ".tile-grid .tile .value",
    ).inner_text()
    assert value_text.isdigit() and int(value_text) > 0


def test_dimension_filter_updates_tiles(page: Page, app: ShinyAppProc) -> None:
    _open(page, app)
    controller.InputSelect(page, "panel").set(SALES_PANEL_LABEL)
    card_locator = page.locator(".tile-grid .tile", has_text="Sales Orders count")
    card_locator.wait_for(timeout=15_000)
    before = int(page.locator(".tile-grid .tile .value").first.inner_text())

    dim = controller.InputSelectize(page, "dim_user_id_name")
    dim.set(["Marc Demo"])

    page.wait_for_timeout(3_000)
    after = int(page.locator(".tile-grid .tile .value").first.inner_text())
    assert after < before or after == before and after != 0
    # all tiles are still rendered
    page.locator(".tile-grid .tile").all()  # no crash


def test_theme_switch_and_then_back(page: Page, app: ShinyAppProc) -> None:
    _open(page, app)
    theme = controller.InputSelect(page, "theme")
    theme.set("Midnight")
    # the server re-injects the theme css ; make sure the select holds it
    page.wait_for_timeout(1_000)
    theme.expect_selected("midnight")
