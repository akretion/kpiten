"""Session handling (shared with the kpiten-core lib)."""

from kpiten_core.session import Session, SessionHandler  # noqa: F401

# Cookie holding the SSO token. Cookies are shared between ports on a host :
# the name is specific to this app (nicegui has its own).
SESSION_COOKIE = "kpiten_shiny_session"
