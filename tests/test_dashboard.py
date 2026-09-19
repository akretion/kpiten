"""End-to-end smoke tests of the Shiny dashboard, against the running stack.

Odoo (:8069) and Shiny (:5000) must be up (`make up`) with a demo database
(`big` by default), else the tests are skipped. A demo user (Marie) goes
through the SSO of Odoo, like a user does from the KpiTen menu.
"""

import os

import pytest
import requests
from playwright.sync_api import Page

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
