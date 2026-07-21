from datetime import datetime, timedelta
from uuid import uuid4


class Session:
    def __init__(self, tk: str, til: datetime):
        self.token = tk
        self.until = til

    @staticmethod
    def is_valid(s: Session):
        if s.until < datetime.now():
            return False
        return True


class SessionHandler:
    sessions: dict[str, Session] = {}

    @staticmethod
    def new_session(ownr_uuid: str) -> str:
        token = str(uuid4())
        SessionHandler.sessions[token] = Session(
            ownr_uuid, datetime.now() + timedelta(days=1)
        )

        return token

    @staticmethod
    def check_session(token: str) -> bool:
        s = SessionHandler.sessions.get(token)
        if s:
            return Session.is_valid(s)
        raise Exception(f"token {token} is unknown.")
