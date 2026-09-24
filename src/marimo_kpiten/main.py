"""FastAPI wrapper exposing the marimo notebook + SSO (mirrors shiny-kpiten).

- POST /            : Odoo posts {"user_uuid": ...}, we validate it against
                      Odoo through the jsonrpc backend and return a session token.
- GET /dashboard/auth?session=...  : validates the token, sets the session
                      cookie, then redirects to the notebook mounted at /dashboard.

marimo runs in "run" mode (`include_code=False`) : the code of the notebook is
ours, the user cannot edit it. The notebook does not read the cookie : the
`SsoMiddleware` resolves it and hands the user to the notebook through
`request.meta`, which the browser cannot set.
"""

import json
import logging
from pathlib import Path

import marimo
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from kpiten_core.backend import Backend

from .sessions import SESSION_COOKIE, SessionHandler

logger = logging.getLogger(__name__)

NOTEBOOKS = Path(__file__).parent / "notebooks"
STATIC = Path(__file__).parent / "static"  # the logo of KpiTen and its favicon

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
    token = SessionHandler.new_session(user_id, db=backend.db)
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
            response = HTMLResponse(
                "<h1>Not connected</h1>"
                "<p>Open the dashboard from Odoo : menu KpiTen → Marimo.</p>",
                status_code=403,
            )
            return await response(scope, receive, send)
        scope["meta"] = {"user_id": session.user_id, "db": session.db}
        return await self.app(scope, receive, send)


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
