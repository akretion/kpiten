from datetime import datetime, timedelta
from uuid import uuid4
from enum import Enum

SESSION_STATE = Enum("SESSION_STATE", [("VALID", 1), ("EXISTS", 0), ("ABSENT", -1)])


class Session:
    VALIDITY_TIME = timedelta(days=1)

    def __init__(self, tk: str, til: datetime):
        self.token = tk
        self.until = til

    @staticmethod
    def is_valid(s: Session):
        if s.until < datetime.now():
            return False
        return True

    def refresh(self):
        self.until = self.until + Session.VALIDITY_TIME


class SessionHandler:
    sessions: dict[str, Session] = {}

    @staticmethod
    def new_session(ownr_uuid: str) -> str:
        token = str(uuid4())
        SessionHandler.sessions[ownr_uuid] = Session(
            token, datetime.now() + timedelta(days=1)
        )

        return token

    @staticmethod
    def check_session(token: str, refresh=True) -> SESSION_STATE:
        """
        A session is considered **valid** if it exists and is not expired.\n
        Returns *VALID* if the session **is valid**; *EXISTS* if it is here but invalid,
        or *ABSENT* if it doesn't exist in memory at all.
        """
        for s in SessionHandler.sessions.items():
            if s[1].token == token and Session.is_valid(s[1]):
                return SESSION_STATE.VALID
            elif s[1].token == token and not Session.is_valid(s[1]):
                if refresh:
                    s[1].refresh()
                    return SESSION_STATE.VALID
                return SESSION_STATE.EXISTS
        return SESSION_STATE.ABSENT

    @staticmethod
    def check_session_from_uuid(ownr_uuid):
        """ """
        s = SessionHandler.sessions.get(ownr_uuid)
        if s:
            return SessionHandler.check_session(s.token)
        else:
            return SESSION_STATE.ABSENT
