"""FastAPI wrapper exposing the shiny dashboard + SSO (mirrors marimo-kpiten).

- POST /            : Odoo posts {"user_uuid": ...}, we validate it against
                      Odoo through the jsonrpc backend and return a session
                      token ; the dashboard syncs the data itself.
- GET /dashboard/auth?session=...  : validates the session token, then
                      redirects to the shiny dashboard mounted at /dashboard.
"""

import json
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

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
        user_id, db=backend.db, lang=backend.get_user_lang(user_id)
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


@this_app.get("/dashboard/tile/{tile_id}")
def tile(tile_id: int, session: str):
    """One tile alone : the iframe of a KPI in its form in Odoo (see `tile_page`)."""
    sso = SessionHandler.get(session)
    if sso is None:
        return HTMLResponse(
            status_code=403,
            content="<h1>Auth failed</h1><p>No session registered for this token.</p>",
        )
    from .tile_page import tile_page

    return HTMLResponse(tile_page(tile_id, sso))


this_app.mount("/dashboard", shiny_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(this_app, host="0.0.0.0", port=5000)
