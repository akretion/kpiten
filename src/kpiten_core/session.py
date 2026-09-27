"""In-memory sessions shared by the dashboard apps.

Each SSO login gets its own `Session` (token -> user + odoo database). The
apps hand the token to the browser in a cookie and look the session up on
every dashboard load : two users logged in at the same time never share a
session, a user id or an Odoo database.

A session of a database whose `kt.config` sets `idle_minutes` ends after that many
minutes without a click or a key : the page (`idle_script`) tells the server the
user is there (`ping`), and sends them to `logout` when they are not.
"""

from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from uuid import uuid4


class Session:
    VALIDITY_TIME = timedelta(days=1)

    def __init__(
        self,
        user_id: int,
        db: str | None = None,
        lang: str | None = None,
        idle_minutes: int = 0,
        odoo_url: str = "",
    ):
        self.token = str(uuid4())
        self.user_id = user_id  # res.users id in `db`
        self.db = db
        self.lang = lang  # res.users.lang at the login : the language of the fronts
        # `kt.config` at the login : the minutes without activity before the logout
        self.idle_minutes = idle_minutes
        self.validity = (
            timedelta(minutes=idle_minutes) if idle_minutes else self.VALIDITY_TIME
        )
        # web.base.url of `db` : the link back to Odoo of the page of the logout
        self.odoo_url = odoo_url
        self.closed = False
        self.until = datetime.now()
        self.refresh()

    @property
    def expired(self) -> bool:
        return self.closed or self.until < datetime.now()

    def refresh(self):
        """Sliding expiry : valid for `validity` after the last use."""
        self.until = datetime.now() + self.validity


class SessionHandler:
    sessions: dict[str, Session] = {}

    @classmethod
    def new_session(
        cls,
        user_id: int,
        db: str | None = None,
        lang: str | None = None,
        idle_minutes: int = 0,
        odoo_url: str = "",
    ) -> str:
        """Open a session for a user (one per SSO login), return its token."""
        cls.purge()
        session = Session(
            user_id, db=db, lang=lang, idle_minutes=idle_minutes, odoo_url=odoo_url
        )
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
    def drop(cls, token: str | None) -> Session | None:
        """End the session of a token (a logout) : a page still open on it is closed
        by its app (`Session.expired`). The session, or None."""
        session = cls.sessions.pop(token, None) if token else None
        if session is not None:
            session.closed = True
        return session

    @classmethod
    def purge(cls):
        """Forget the expired sessions."""
        for token in [t for t, s in cls.sessions.items() if s.expired]:
            cls.sessions.pop(token, None)


# the page counts the minutes without a click or a key ; the tabs of an app share the
# last activity (localStorage), so an idle tab does not log out the one in use. It
# pings the server at most once a minute while the user is active.
IDLE_JS = """
(function () {
  if (window.__kpitenIdle) { return; }
  window.__kpitenIdle = true;
  var limit = %(minutes)d * 60000, base = %(base)s, key = "kpiten-last-active";
  var last = Date.now(), pinged = 0, gone = false;
  function shared() {
    try { return parseInt(localStorage.getItem(key), 10) || 0; } catch (e) { return 0; }
  }
  function out() {
    if (gone) { return; }
    gone = true;
    window.location.replace(base + "/logout?idle=1");
  }
  function active() {
    last = Date.now();
    try { localStorage.setItem(key, String(last)); } catch (e) {}
    if (last - pinged < 60000) { return; }
    pinged = last;
    fetch(base + "/ping", {method: "POST", credentials: "same-origin"})
      .then(function (r) { if (r.status === 403) { out(); } })
      .catch(function () {});
  }
  ["mousedown", "mousemove", "keydown", "wheel", "touchstart", "scroll"]
    .forEach(function (name) {
      document.addEventListener(name, active, {capture: true, passive: true});
    });
  active();
  setInterval(function () {
    if (Date.now() - Math.max(last, shared()) >= limit) { out(); }
  }, 15000);
})();
"""


def idle_script(minutes: int, base: str) -> str:
    """The script of a page of an app (`base` : the path of the app, i.e.
    `/dashboard`) ; empty when the database never logs out."""
    if not minutes:
        return ""
    return IDLE_JS % {"minutes": minutes, "base": repr(base)}


# the action of the menu KpiTen of Odoo (its home page : a button per front)
HOME_ACTION = "kpiten.kt_home_server_action"


def odoo_url_of(db: str | None = None) -> str:
    """web.base.url of the database (the default one when None) ; "" when Odoo does
    not answer : the pages then show no link."""
    from kpiten_core.backend import Backend

    try:
        return Backend.create(db=db).get_base_url()
    except Exception:
        return ""


def reconnect_html(tr, front: str, odoo_url: str) -> str:
    """« Open the dashboard from Odoo » and, when Odoo is known, a button to the menu
    KpiTen there."""
    text = escape(
        tr("Open the dashboard from Odoo : menu KpiTen → {front}.", front=front)
    )
    if not odoo_url:
        return f"<p>{text}</p>"
    url = escape(f"{odoo_url.rstrip('/')}/odoo/action-{HOME_ACTION}", quote=True)
    return (
        f'<p>{text}</p><a class="kt-msg-button" href="{url}">'
        f"{escape(tr('Open KpiTen in Odoo'))} →</a>"
    )


# the card of a page without a dashboard, over a made-up chart
MESSAGE_HTML = Path(__file__).parent / "assets" / "message.html"


def message_html(title: str, body: str) -> str:
    """The card (`title`, `body` : html) over its chart, to put in a page."""
    return (
        MESSAGE_HTML.read_text()
        .replace("{{title}}", escape(title))
        .replace("{{body}}", body)
    )


def message_page(title: str, body: str, lang: str = "en", icon: str = "") -> str:
    """`message_html` as a whole page (a front outside of its app) ; `icon` : the url
    of the favicon of the front."""
    favicon = f'<link rel="icon" href="{escape(icon, quote=True)}">' if icon else ""
    return (
        f'<!doctype html><html lang="{escape(lang[:2], quote=True)}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{favicon}<title>{escape(title)} · KpiTen</title></head>"
        f'<body style="margin: 0">{message_html(title, body)}</body></html>'
    )


def logged_out_html(
    tr, idle: bool, front: str, odoo_url: str = "", icon: str = ""
) -> str:
    """The page of a logout ; `idle` : after the minutes without activity."""
    text = (
        tr("You were logged out after a time without activity.")
        if idle
        else tr("You are logged out.")
    )
    return message_page(
        tr("Logged out"),
        f"<p>{escape(text)}</p>{reconnect_html(tr, front, odoo_url)}",
        getattr(tr, "lang", "en"),
        icon,
    )


def not_connected_html(
    tr, front: str, odoo_url: str, page: bool = False, icon: str = ""
) -> str:
    """No session : the card to put in a page of the app, or a whole page (`page`,
    with the favicon `icon`)."""
    title, body = tr("Not connected"), reconnect_html(tr, front, odoo_url)
    if page:
        return message_page(title, body, getattr(tr, "lang", "en"), icon)
    return message_html(title, body)
