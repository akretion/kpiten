"""In-memory sessions shared by the dashboard apps.

Each SSO login gets its own `Session` (token -> user + odoo database). The
apps hand the token to the browser in a cookie and look the session up on
every dashboard load : two users logged in at the same time never share a
session, a user id or an Odoo database.
"""

from datetime import datetime, timedelta
from uuid import uuid4


class Session:
    VALIDITY_TIME = timedelta(days=1)

    def __init__(self, user_id: int, db: str | None = None, lang: str | None = None):
        self.token = str(uuid4())
        self.user_id = user_id  # res.users id in `db`
        self.db = db
        self.lang = lang  # res.users.lang at the login : the language of the fronts
        self.until = datetime.now()
        self.refresh()

    @property
    def expired(self) -> bool:
        return self.until < datetime.now()

    def refresh(self):
        """Sliding expiry : valid for `VALIDITY_TIME` after the last use."""
        self.until = datetime.now() + self.VALIDITY_TIME


class SessionHandler:
    sessions: dict[str, Session] = {}

    @classmethod
    def new_session(
        cls, user_id: int, db: str | None = None, lang: str | None = None
    ) -> str:
        """Open a session for a user (one per SSO login), return its token."""
        cls.purge()
        session = Session(user_id, db=db, lang=lang)
        cls.sessions[session.token] = session
        return session.token

    @classmethod
    def get(cls, token: str | None) -> Session | None:
        """The valid session of a token (its expiry is renewed), else None."""
        session = cls.sessions.get(token) if token else None
        if session is None:
            return None
        if session.expired:
            cls.sessions.pop(token, None)
            return None
        session.refresh()
        return session

    @classmethod
    def check_session(cls, token: str | None) -> bool:
        return cls.get(token) is not None

    @classmethod
    def purge(cls):
        """Forget the expired sessions."""
        for token in [t for t, s in cls.sessions.items() if s.expired]:
            cls.sessions.pop(token, None)
