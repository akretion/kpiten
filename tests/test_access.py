"""Per-user isolation : sessions and row/column restrictions of the store."""

import datetime
from types import SimpleNamespace

import polars as pl

from kpiten_core import loaders
from kpiten_core.session import SessionHandler


def test_sessions_are_independent():
    alice = SessionHandler.new_session(1, db="db_a")
    bob = SessionHandler.new_session(2, db="db_b")
    assert alice != bob
    a, b = SessionHandler.get(alice), SessionHandler.get(bob)
    assert (a.user_id, a.db) == (1, "db_a")
    assert (b.user_id, b.db) == (2, "db_b")
    # a token only opens its own session
    assert SessionHandler.get("not-a-token") is None
    assert SessionHandler.get(None) is None
    assert SessionHandler.get("") is None


def test_session_expiry():
    token = SessionHandler.new_session(1, db="db_a")
    SessionHandler.get(token).until = datetime.datetime.now() - datetime.timedelta(1)
    assert not SessionHandler.check_session(token)
    assert token not in SessionHandler.sessions
    # using a session renews it
    fresh = SessionHandler.new_session(1, db="db_a")
    soon = datetime.datetime.now() + datetime.timedelta(minutes=1)
    SessionHandler.sessions[fresh].until = soon
    assert SessionHandler.get(fresh).until > soon


def test_purge_forgets_only_the_expired():
    old = SessionHandler.new_session(1)
    SessionHandler.sessions[old].until = datetime.datetime.now() - datetime.timedelta(1)
    live = SessionHandler.new_session(2)  # new_session purges
    assert old not in SessionHandler.sessions
    assert live in SessionHandler.sessions


def test_restrict_rows():
    df = pl.DataFrame({"id": [1, 2, 3, 4], "v": list("abcd")})
    kept = loaders.restrict_rows(df, pl.Series("id", [2, 4, 99], dtype=pl.Int64))
    assert kept["id"].to_list() == [2, 4]
    assert loaders.restrict_rows(df, pl.Series("id", [], dtype=pl.Int64)).is_empty()


ORDERS = pl.DataFrame({"id": [1, 2, 3], "name": ["S1", "S2", "S3"]})
PURCHASES = pl.DataFrame({"id": [7, 8], "name": ["P7", "P8"]})


class FakeStorage:
    @staticmethod
    def list_table_names():
        return ["sale.order", "purchase.order", "broken"]

    @staticmethod
    def scan_df(table, allowed_fields=None, lang=None):
        df = {"sale.order": ORDERS, "purchase.order": PURCHASES}.get(table, ORDERS)
        return df.lazy()


class FakeBackend:
    """A user who may read sale orders 1 and 3, no purchase, a broken table."""

    env = SimpleNamespace(db="testdb")

    def get_user_lang(self, user_id):
        return "en_US"

    def get_allowed_fields(self, table, user_id):
        return ["id", "name"]

    def get_access_query(self, table, user_id):
        if table == "broken":
            raise RuntimeError("odoo is down")
        return {"sale.order": "SELECT id FROM sale_order", "purchase.order": ""}[table]


def test_user_store_applies_the_record_rules(monkeypatch):
    monkeypatch.setattr(loaders, "DFStorage", FakeStorage)
    monkeypatch.setattr(
        loaders,
        "_read_sql_df",
        lambda uri, query: pl.DataFrame({"id": [1, 3]}, schema={"id": pl.Int64}),
    )
    store = loaders.user_store(FakeBackend(), user_id=8)
    # lazy : nothing is read until a tile collects
    assert isinstance(store["sale.order"], pl.LazyFrame)
    assert store["sale.order"].collect()["id"].to_list() == [1, 3]
    # no read access to the model : the table is there, without any row
    assert store["purchase.order"].collect().is_empty()
    # access unresolved : the table is left out, never shown unrestricted
    assert "broken" not in store


def test_user_store_is_scoped_to_the_database(monkeypatch):
    seen = []

    class SpyStorage(FakeStorage):
        @staticmethod
        def list_table_names():
            from kpiten_core import env

            seen.append(env.active_db())
            return []

    monkeypatch.setattr(loaders, "DFStorage", SpyStorage)
    loaders.user_store(FakeBackend(), user_id=8)
    assert seen == ["testdb"]
