"""In-memory session handling shared by the dashboard apps.

Mirrors the marimo-kpiten `session_handler`. A `Session` is a token with an
expiry, refreshed on each use ; `SessionHandler` keeps the sessions of the
single (SSO) user along with the active odoo database.
"""

from datetime import datetime, timedelta
from uuid import uuid4


class Session:
    VALIDITY_TIME = timedelta(days=1)

    def __init__(self, db: str | None = None):
        self.token = str(uuid4())
        self.until = datetime.now() + self.VALIDITY_TIME
        self.db = db
        self.refresh()

    def refresh(self):
        self.until = self.until + self.VALIDITY_TIME


class SessionHandler:
    sessions: dict[str, Session] = {}
    user_id: int | None = None  # current (single-user dev app)
    db: str | None = None  # odoo database of the current session

    @classmethod
    def new_session(cls, user_id: int, db: str | None = None) -> str:
        if cls.user_id == user_id and cls.db == db and cls.sessions:
            token = next(iter(cls.sessions))
            cls.check_session(token)
            return token
        session = Session(db=db)
        cls.sessions[session.token] = session
        cls.user_id = user_id
        cls.db = db
        return session.token

    @classmethod
    def check_session(cls, token: str) -> bool:
        session = cls.sessions.get(token)
        if not session:
            return False
        if session.until < datetime.now():
            return False
        session.refresh()
        return True
