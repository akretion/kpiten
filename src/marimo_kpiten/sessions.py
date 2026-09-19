"""Session handling (shared with the kpiten-core lib)."""

from kpiten_core.session import Session, SessionHandler  # noqa: F401

# Cookie holding the SSO token. Cookies are shared between ports on a host :
# the name is specific to this app (shiny and nicegui have their own).
SESSION_COOKIE = "kpiten_marimo_session"
