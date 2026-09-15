"""FastAPI wrapper exposing the shiny dashboard + SSO (mirrors marimo-kpiten).

- POST /            : Odoo posts {"user_uuid": ...}, we validate it against
                      Odoo through the jsonrpc backend, refresh the data
                      snapshot, and return a session token.
- GET /dashboard/auth?session=...  : validates the session token, then
                      redirects to the shiny dashboard mounted at /dashboard.
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from kpiten_core.backend import Backend
from kpiten_core.service import service as kpiten_service

from .app import app as shiny_app
from .sessions import SessionHandler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    # kpiten-core owns the background sync (one queue per database) ; the app
    # only requests loads / refreshes and lets the service complete in the
    # background without overloading Odoo.
    kpiten_service.start()
    try:
        yield
    finally:
        kpiten_service.stop()


this_app = FastAPI(lifespan=lifespan)


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
    try:
        from kpiten_core import env

        env.current_db = backend.db
        # ask kpiten-core to load this db ; the background service fills the
        # older data progressively (the dashboard seeds it on first render).
        kpiten_service.request_load(backend.db, wait=False)
    except Exception:
        logger.exception("data refresh failed")
        return Response(
            status_code=500,
            content=json.dumps(
                {"error": "The server is unavailable. Please try again later !"}
            ),
        )
    token = SessionHandler.new_session(user_id, db=backend.db)
    return Response(status_code=200, content=json.dumps({"session": token}))


@this_app.get("/dashboard/auth")
def check(session: str):
    if not SessionHandler.check_session(session):
        return HTMLResponse(
            status_code=403,
            content="<h1>Auth failed</h1><p>No session registered for this token.</p>",
        )
    return Response(status_code=303, headers={"Location": "/dashboard"})


this_app.mount("/dashboard", shiny_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(this_app, host="0.0.0.0", port=5000)
