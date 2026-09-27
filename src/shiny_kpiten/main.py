"""FastAPI wrapper exposing the shiny dashboard + SSO (mirrors marimo-kpiten).

- POST /            : Odoo posts {"user_uuid": ...}, we validate it against
                      Odoo through the jsonrpc backend and return a session
                      token ; the dashboard syncs the data itself.
- GET /dashboard/auth?session=...  : validates the session token, then
                      redirects to the shiny dashboard mounted at /dashboard.
"""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from kpiten_core import config as core_config
from kpiten_core import i18n
from kpiten_core import session as core_session
from kpiten_core.backend import Backend

from .app import app as shiny_app
from .sessions import SESSION_COOKIE, SessionHandler

logger = logging.getLogger(__name__)


this_app = FastAPI()


@this_app.post("/")
def auth(payload: dict):
    if not payload or not payload.get("user_uuid"):
        return Response(
            status_code=403,
            content=json.dumps({"error": "No user_uuid provided"}),
        )
    db = payload.get("db")
    backend = Backend.create(db=db)
    user_id = backend.check_uuid(payload["user_uuid"])
    if user_id is None:
        return Response(
            status_code=403,
            content=json.dumps({"error": "No user matches this uuid"}),
        )
    from kpiten_core import env

    # scope the parquet store to this db ; the dashboard triggers the actual
    # sync itself (empty store on first render, or the "Refresh data" button).
    env.current_db = backend.db
    # the language of the user in Odoo : the one of the dashboard
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
    # the token goes in a cookie : the dashboard reads it to know who is
    # connected (one session per user, nothing shared between users)
    response = Response(status_code=303, headers={"Location": "/dashboard"})
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
            "Shiny",
            sso.odoo_url if sso else core_session.odoo_url_of(),
            icon="/dashboard/static/kpiten.png",
        )
    )
    response.delete_cookie(SESSION_COOKIE, path="/dashboard")
    return response


@this_app.get("/dashboard/tile/{tile_id}")
def tile(tile_id: int, session: str, thumb: str | None = None):
    """One tile alone : the iframe of a KPI in its form in Odoo (see `tile_page`) ;
    `thumb` : Odoo asks for a new thumbnail, made from this definition."""
    sso = SessionHandler.get(session)
    if sso is None:
        return HTMLResponse(
            status_code=403,
            content="<h1>Auth failed</h1><p>No session registered for this token.</p>",
        )
    from .tile_page import tile_page

    return HTMLResponse(tile_page(tile_id, sso, thumb))


@this_app.post("/dashboard/tile/{tile_id}/thumbnail")
def tile_thumbnail(tile_id: int, session: str, payload: dict):
    """The picture of a tile its page took (`tile_page._capture`) -> the thumbnail of
    the KPI ; Odoo makes it small and blurred, and refuses it when the definition
    changed since (`kt.kpi.set_thumbnail`)."""
    sso = SessionHandler.get(session)
    if sso is None:
        return JSONResponse(status_code=403, content={"error": "Not connected"})
    try:
        backend = Backend.create(db=sso.db)
        done = backend.call(
            backend.kpi_model,
            "set_thumbnail",
            ids=[tile_id],
            image=str(payload.get("image") or ""),
            key=str(payload.get("key") or ""),
        )
    except Exception:
        logger.exception("the thumbnail of KPI %s failed", tile_id)
        return JSONResponse(status_code=500, content={"error": "Thumbnail failed"})
    return JSONResponse(content={"ok": bool(done)})


this_app.mount("/dashboard", shiny_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(this_app, host="0.0.0.0", port=5000)
