"""FastAPI wrapper exposing the marimo notebook + SSO (mirrors shiny-kpiten).

- POST /            : Odoo posts {"user_uuid": ...}, we validate it against
                      Odoo through the jsonrpc backend and return a session token.
- GET /dashboard/auth?session=...  : validates the token, sets the session
                      cookie, then redirects to the notebook mounted at /dashboard.

marimo runs in "run" mode (`include_code=False`) : the code of the notebook is
ours, the user cannot edit it. The notebook does not read the cookie : the
`SsoMiddleware` resolves it and hands the user to the notebook through
`request.meta`, which the browser cannot set. It also adds to each page the script
that logs the user out after the minutes without activity of `kt.config`
(`kpiten_core.session.idle_script`).
"""

import json
import logging
from pathlib import Path

import marimo
from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from kpiten_core import config as core_config
from kpiten_core import i18n
from kpiten_core import session as core_session
from kpiten_core.backend import Backend

from .sessions import SESSION_COOKIE, SessionHandler

logger = logging.getLogger(__name__)

NOTEBOOKS = Path(__file__).parent / "notebooks"
STATIC = Path(__file__).parent / "static"  # the logo of KpiTen and its favicon
FAVICON_URL = "/dashboard/favicon.ico"  # the pages of the logout, of no session

this_app = FastAPI()


@this_app.get("/dashboard/kpiten.png")
def kpiten_logo():
    """The mark of KpiTen, drawn in the header of the pages."""
    return FileResponse(STATIC / "kpiten.png", media_type="image/png")


@this_app.get("/dashboard/favicon.ico")
@this_app.get("/dashboard/{notebook}/favicon.ico")
def favicon(notebook: str | None = None):
    """The icon of the tab : the wheel of KpiTen instead of the one of marimo (the pages
    ask `./favicon.ico`, at the list and at each notebook)."""
    return FileResponse(STATIC / "favicon.png", media_type="image/png")


@this_app.get("/")
def home():
    """Opened by hand : the list of analyses, or "Not connected" without a session."""
    return RedirectResponse("/dashboard/")


@this_app.post("/")
def auth(payload: dict):
    if not payload or not payload.get("user_uuid"):
        return Response(
            status_code=403,
            content=json.dumps({"error": "No user_uuid provided"}),
        )
    backend = Backend.create(db=payload.get("db"))
    user_id = backend.check_uuid(payload["user_uuid"])
    if user_id is None:
        return Response(
            status_code=403,
            content=json.dumps({"error": "No user matches this uuid"}),
        )
    token = SessionHandler.new_session(
        user_id,
        db=backend.db,
        lang=backend.get_user_lang(user_id),
        idle_minutes=core_config.idle_minutes(backend.get_chart_config()),
        odoo_url=backend.get_base_url(),
    )
    return Response(status_code=200, content=json.dumps({"session": token}))


@this_app.get("/dashboard/auth")
def check(session: str):
    sso = SessionHandler.get(session)
    if sso is None:
        return HTMLResponse(
            status_code=403,
            content="<h1>Auth failed</h1><p>No session registered for this token.</p>",
        )
    response = Response(status_code=303, headers={"Location": "/dashboard/"})
    response.set_cookie(
        SESSION_COOKIE,
        session,
        httponly=True,
        samesite="lax",
        path="/dashboard",
        max_age=int(sso.VALIDITY_TIME.total_seconds()),
    )
    return response


@this_app.post("/dashboard/ping")
def ping(request: Request):
    """The user is active on the page (`kpiten_core.session.idle_script`) : their
    session lives on ; 403 when it ended."""
    if SessionHandler.get(request.cookies.get(SESSION_COOKIE)) is None:
        return JSONResponse(status_code=403, content={"error": "Not connected"})
    return JSONResponse(content={"ok": True})


@this_app.get("/dashboard/logout")
def logout(request: Request, idle: bool = False):
    """End the session (`idle` : after the minutes without activity of kt.config)."""
    sso = SessionHandler.drop(request.cookies.get(SESSION_COOKIE))
    tr = i18n.translator(sso.lang if sso else request.headers.get("accept-language"))
    response = HTMLResponse(
        core_session.logged_out_html(
            tr,
            idle,
            "Marimo",
            sso.odoo_url if sso else core_session.odoo_url_of(),
            icon=FAVICON_URL,
        )
    )
    response.delete_cookie(SESSION_COOKIE, path="/dashboard")
    return response


class SsoMiddleware:
    """Let the notebook in only with a valid session, and tell it who is there.

    `scope["meta"]` is what marimo exposes as `mo.app_meta().request.meta`. It is
    overwritten here, so a client cannot pass its own.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        token = HTTPConnection(scope).cookies.get(SESSION_COOKIE)
        session = SessionHandler.get(token)
        if session is None:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4403})
            tr = i18n.translator(HTTPConnection(scope).headers.get("accept-language"))
            response = HTMLResponse(
                core_session.not_connected_html(
                    tr,
                    "Marimo",
                    core_session.odoo_url_of(),
                    page=True,
                    icon=FAVICON_URL,
                ),
                status_code=403,
            )
            return await response(scope, receive, send)
        scope["meta"] = {"user_id": session.user_id, "db": session.db}
        script = core_session.idle_script(session.idle_minutes, "/dashboard")
        if scope["type"] != "http" or not script:
            return await self.app(scope, receive, send)
        return await self.app(scope, receive, with_script(send, script))


def with_script(send: Send, script: str) -> Send:
    """`send` that adds `script` at the end of the head of an html page (a page of
    marimo) ; the other responses pass as they are."""
    start: dict = {}
    body: list[bytes] = []

    async def wrapped(message):
        if message["type"] == "http.response.start":
            headers = dict(message.get("headers") or [])
            html = headers.get(b"content-type", b"").startswith(b"text/html")
            if not html or b"content-encoding" in headers:
                return await send(message)
            start.update(message)
            return
        if not start:
            return await send(message)
        body.append(message.get("body", b""))
        if message.get("more_body"):
            return
        page = b"".join(body).replace(
            b"</head>", f"<script>{script}</script></head>".encode(), 1
        )
        headers = [
            (k, v) for k, v in start.get("headers") or [] if k != b"content-length"
        ]
        headers.append((b"content-length", str(len(page)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": page})

    return wrapped


# /dashboard/ is the list of the analyses (`_index.py`), /dashboard/<name>/ one of
# them (`notebooks/<name>.py`) : a name starting with "_" is not served
marimo_app = (
    marimo.create_asgi_app(include_code=False)
    .with_app(
        path="/dashboard",
        root=str(NOTEBOOKS / "_index.py"),
        middleware=[SsoMiddleware],
    )
    .with_dynamic_directory(
        path="/dashboard", directory=str(NOTEBOOKS), middleware=[SsoMiddleware]
    )
    .build()
)
this_app.mount("/", marimo_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(this_app, host="0.0.0.0", port=5002)
