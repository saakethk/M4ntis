"""Strategy visibility tests that do not require Tiger Data."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import helpers.auth as auth
import helpers.strategies as strategies
import main
from helpers.auth import User

SOFTWARE = Path(__file__).resolve().parents[1]
DOCUMENT = {"kind": "m4ntis.strategy/v1", "nodes": []}
IR = {"kind": "m4ntis.strategy-ir/v1", "ops": []}
OWNER = User(4, "owner@example.com")


def _sign_in(client: TestClient) -> None:
    client.cookies.set("session", "raw-token")


class VisibilityRulesTest(unittest.TestCase):
    def test_private_strategy_is_visible_only_to_its_owner(self) -> None:
        self.assertTrue(strategies.can_view(1, "private", 1))
        self.assertFalse(strategies.can_view(1, "private", 2))
        self.assertTrue(strategies.can_edit(1, 1))
        self.assertFalse(strategies.can_edit(1, 2))

    def test_public_strategy_is_viewable_and_still_owner_edited(self) -> None:
        self.assertTrue(strategies.can_view(1, "public", 2))
        self.assertFalse(strategies.can_edit(1, 2))
        self.assertTrue(strategies.can_edit(1, 1))

    def test_visibility_rejects_share_roles(self) -> None:
        for value in ("view", "edit", "shared", "", None):
            with self.assertRaises(ValueError):
                strategies.normalize_visibility(value)
        self.assertEqual(strategies.normalize_visibility("private"), "private")
        self.assertEqual(strategies.normalize_visibility("public"), "public")

    def test_new_strategy_is_private(self) -> None:
        values = strategies.new_strategy_values(9, "  Trend  ", DOCUMENT, None)
        self.assertEqual(values["user_id"], 9)
        self.assertEqual(values["name"], "Trend")
        self.assertEqual(values["visibility"], "private")
        self.assertEqual(values["document"], DOCUMENT)
        self.assertIsNone(values["ir"])

    def test_new_strategy_can_be_public(self) -> None:
        values = strategies.new_strategy_values(9, "Trend", DOCUMENT, None, "public")
        self.assertEqual(values["visibility"], "public")
        self.assertEqual(values["user_id"], 9)

    def test_copy_is_a_private_row_for_the_caller(self) -> None:
        document = {"nodes": [1]}
        ir = {"ops": [2]}
        payload = strategies.copy_payload(9, "Trend", document, ir)
        self.assertEqual(
            payload,
            {
                "user_id": 9,
                "name": "Trend",
                "visibility": "private",
                "document": {"nodes": [1]},
                "ir": {"ops": [2]},
            },
        )
        payload["document"]["nodes"].append(3)
        payload["ir"]["ops"].append(4)
        self.assertEqual(document, {"nodes": [1]})
        self.assertEqual(ir, {"ops": [2]})

    def test_list_query_omits_the_document(self) -> None:
        folded = " ".join(strategies.LIST_SQL.split())
        self.assertNotIn("document", folded)
        self.assertNotIn("ir", folded)
        self.assertIn("id, name, visibility, updated_at", folded)

    def test_schema_uses_visibility_and_the_loader_drops_shares(self) -> None:
        sql = (SOFTWARE / "database" / "sql" / "strategies.sql").read_text()
        loader = (SOFTWARE / "database" / "load_strategies.py").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS strategies", sql)
        self.assertIn("visibility TEXT NOT NULL DEFAULT 'private'", sql)
        self.assertIn("CHECK (visibility IN ('private', 'public'))", sql)
        self.assertIn("strategies_user_id_idx", sql)
        self.assertNotIn("strategy_shares", sql)
        self.assertIn("DROP TABLE IF EXISTS strategy_shares", loader)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'",
            loader,
        )
        self.assertIn("strategies_visibility_check", loader)
        self.assertIn("if existing is not None", loader)
        versions = (SOFTWARE / "database" / "sql" / "discussions_backtests.sql").read_text()
        self.assertIn("kind TEXT NOT NULL DEFAULT 'save'", versions)
        self.assertIn("ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'save'", versions)


class _SessionStore:
    """Committed rows a login connection can see. Uncommitted inserts stay invisible."""

    def __init__(self, users: set[tuple[int, str, str]]) -> None:
        self.users_by_email = {
            email: (user_id, email, password_hash) for user_id, email, password_hash in users
        }
        self.sessions: dict[str, tuple[int, datetime]] = {}


class _SessionResult:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row


class _SessionTx:
    def __init__(self, conn: "_SessionConn") -> None:
        self.conn = conn
        self.outer = False

    def __enter__(self) -> "_SessionTx":
        # psycopg only COMMITs when the connection was idle. Otherwise this
        # is a savepoint and close() rolls the work back.
        self.outer = self.conn.status == "idle"
        if self.outer:
            self.conn.status = "intrans"
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is not None:
            self.conn.rollback()
            return False
        if self.outer:
            self.conn.commit()
        return False


class _SessionConn:
    def __init__(self, store: _SessionStore, *, in_transaction: bool) -> None:
        self.store = store
        self.status = "intrans" if in_transaction else "idle"
        self._pending: list[tuple[str, object]] = []
        self.closed = False

    def transaction(self) -> _SessionTx:
        return _SessionTx(self)

    def execute(self, sql: str, params: object = None) -> _SessionResult:
        folded = " ".join(sql.split())
        if self.status == "idle":
            self.status = "intrans"
        self._pending.append((folded, params))
        if "password_hash" in folded:
            email = params[0] if isinstance(params, tuple) else None
            return _SessionResult(self.store.users_by_email.get(email))
        if folded.startswith("INSERT INTO sessions"):
            return _SessionResult(None)
        if "FROM sessions" in folded:
            token_hash = params[0] if isinstance(params, tuple) else None
            found = self.store.sessions.get(token_hash)
            if found is None:
                return _SessionResult(None)
            user_id, expires_at = found
            if expires_at <= datetime.now(timezone.utc):
                return _SessionResult(None)
            for row in self.store.users_by_email.values():
                if row[0] == user_id:
                    return _SessionResult((row[0], row[1]))
            return _SessionResult(None)
        return _SessionResult(None)

    def commit(self) -> None:
        if self.status != "intrans":
            return
        for sql, params in self._pending:
            if sql.startswith("INSERT INTO sessions") and isinstance(params, tuple):
                token_hash, user_id, expires_at = params
                self.store.sessions[str(token_hash)] = (int(user_id), expires_at)
        self._pending = []
        self.status = "idle"

    def rollback(self) -> None:
        self._pending = []
        self.status = "idle"

    def close(self) -> None:
        if self.status == "intrans":
            self.rollback()
        self.closed = True


class StrategyRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_routes_require_a_session(self) -> None:
        with patch.object(auth, "user_from_token", return_value=None):
            created = self.client.post(
                "/strategies", json={"name": "Trend", "document": DOCUMENT}
            )
            listed = self.client.get("/strategies")
            fetched = self.client.get("/strategies/1")
            updated = self.client.put("/strategies/1", json={"name": "Trend"})
            copied = self.client.post("/strategies/1/copy")
            versions = self.client.get("/strategies/1/versions")
            reverted = self.client.post("/strategies/1/versions/2/revert")
        self.assertEqual(
            [
                created.status_code,
                listed.status_code,
                fetched.status_code,
                updated.status_code,
                copied.status_code,
                versions.status_code,
                reverted.status_code,
            ],
            [401, 401, 401, 401, 401, 401, 401],
        )

    def test_create_stores_a_private_strategy_for_the_session_user(self) -> None:
        stored = {
            "id": 3,
            "name": "Trend",
            "visibility": "private",
            "updated_at": "2026-09-26T00:00:00+00:00",
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "create_strategy", return_value=stored) as create,
        ):
            response = self.client.post(
                "/strategies", json={"name": "Trend", "document": DOCUMENT, "ir": IR}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), stored)
        create.assert_called_once_with(4, "Trend", DOCUMENT, IR, "private")

    def test_create_rejects_a_blank_name_bad_visibility_and_user_id(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            blank = self.client.post(
                "/strategies", json={"name": "  ", "document": DOCUMENT}
            )
        self.assertEqual(blank.status_code, 400)

        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "create_strategy") as create,
        ):
            bad_visibility = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "visibility": "edit"},
            )
            user_id = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "user_id": 9},
            )
            not_object = self.client.post(
                "/strategies", json={"name": "Trend", "document": [1]}
            )
        self.assertEqual(bad_visibility.status_code, 400)
        self.assertEqual(user_id.status_code, 422)
        self.assertEqual(not_object.status_code, 422)
        create.assert_not_called()

    def test_create_stores_a_public_strategy_when_asked(self) -> None:
        stored = {
            "id": 3,
            "name": "Trend",
            "visibility": "public",
            "updated_at": "2026-09-26T00:00:00+00:00",
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "create_strategy", return_value=stored) as create,
        ):
            response = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "visibility": "public"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), stored)
        create.assert_called_once_with(4, "Trend", DOCUMENT, None, "public")

    def test_create_rejects_share_fields(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            role = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "role": "edit"},
            )
            share = self.client.post(
                "/strategies",
                json={"name": "Trend", "document": DOCUMENT, "share_with_user": 8},
            )
        self.assertEqual(role.status_code, 422)
        self.assertEqual(share.status_code, 422)

    def test_login_cookie_lists_strategies_and_a_missing_cookie_is_rejected(self) -> None:
        password_hash = auth.hash_password("correct horse")
        store = _SessionStore(
            {(7, "person@example.com", password_hash)}
        )

        def connect() -> _SessionConn:
            # connect() leaves SET TIME ZONE uncommitted, so login receives
            # a connection that is already in a transaction.
            return _SessionConn(store, in_transaction=True)

        with patch.object(auth, "_connect", side_effect=connect):
            logged_in = self.client.post(
                "/auth/login",
                json={"email": "person@example.com", "password": "correct horse"},
            )
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(logged_in.json(), {"id": 7, "email": "person@example.com"})
        token = logged_in.cookies.get("session")
        self.assertIsNotNone(token)
        self.assertIn("path=/", logged_in.headers["set-cookie"].lower())
        self.assertIn(auth._token_hash(token), store.sessions)

        with (
            patch.object(auth, "_connect", side_effect=connect),
            patch.object(strategies, "list_strategies", return_value=[]) as listed,
        ):
            listed_response = self.client.get("/strategies")
        self.assertEqual(listed_response.status_code, 200)
        self.assertEqual(listed_response.json(), [])
        listed.assert_called_once_with(7)

        self.client.cookies.clear()
        with patch.object(auth, "_connect", side_effect=connect):
            missing = self.client.get("/strategies")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["detail"], "Not signed in")

    def test_list_returns_summaries_without_documents(self) -> None:
        summaries = [
            {
                "id": 3,
                "name": "Trend",
                "visibility": "private",
                "updated_at": "2026-09-26T00:00:00+00:00",
            }
        ]
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_strategies", return_value=summaries),
        ):
            response = self.client.get("/strategies")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), summaries)
        self.assertNotIn("document", response.json()[0])

    def test_get_returns_the_document_and_owned_flag(self) -> None:
        row = {
            "id": 3,
            "user_id": 9,
            "name": "Trend",
            "visibility": "public",
            "document": DOCUMENT,
            "ir": None,
            "updated_at": "2026-09-26T00:00:00+00:00",
            "created_at": "2026-09-26T00:00:00+00:00",
            "owned": False,
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", return_value=row),
        ):
            response = self.client.get("/strategies/3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document"], DOCUMENT)
        self.assertFalse(response.json()["owned"])

    def test_get_hides_strategies_the_user_cannot_view(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "get_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            response = self.client.get("/strategies/3")
        self.assertEqual(response.status_code, 404)

    def test_put_returns_the_updated_summary(self) -> None:
        stored = {
            "id": 3,
            "name": "Trend",
            "visibility": "public",
            "updated_at": "2026-09-26T00:00:00+00:00",
        }
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "update_strategy", return_value=stored) as update,
        ):
            response = self.client.put("/strategies/3", json={"visibility": "public"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stored)
        update.assert_called_once_with(
            4,
            3,
            name=strategies.UNSET,
            document=strategies.UNSET,
            ir=strategies.UNSET,
            visibility="public",
        )

    def test_put_rejects_an_empty_body(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "update_strategy", side_effect=ValueError("No fields to update")
            ),
        ):
            response = self.client.put("/strategies/3", json={})
        self.assertEqual(response.status_code, 400)

    def test_put_rejects_non_owners_and_bad_visibility(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(
                strategies, "update_strategy", side_effect=strategies.StrategyForbidden()
            ) as update,
        ):
            forbidden = self.client.put("/strategies/3", json={"visibility": "public"})
        self.assertEqual(forbidden.status_code, 403)
        update.assert_called_once()

        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "update_strategy") as update,
        ):
            rejected = self.client.put("/strategies/3", json={"visibility": "edit"})
        self.assertEqual(rejected.status_code, 400)
        update.assert_not_called()

        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "update_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            missing = self.client.put("/strategies/99", json={"name": "Trend"})
        self.assertEqual(missing.status_code, 404)

    def test_put_rejects_a_share_field(self) -> None:
        _sign_in(self.client)
        with patch.object(auth, "user_from_token", return_value=OWNER):
            response = self.client.put(
                "/strategies/3", json={"visibility": "public", "role": "edit"}
            )
        self.assertEqual(response.status_code, 422)

    def test_copy_returns_the_new_id(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "copy_strategy", return_value=12) as copy,
        ):
            response = self.client.post("/strategies/3/copy")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": 12})
        copy.assert_called_once_with(4, 3)

    def test_copy_is_not_found_when_the_user_cannot_view(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "copy_strategy", side_effect=strategies.StrategyNotFound()),
        ):
            response = self.client.post("/strategies/3/copy")
        self.assertEqual(response.status_code, 404)

    def test_versions_list_and_revert_for_the_owner(self) -> None:
        listed = [{"id": 8, "name": "Earlier", "created_at": "2026-09-26T12:00:00+00:00"}]
        restored = {"id": 3, "name": "Earlier", "document": {"name": "Earlier"}, "ir": None}
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_versions", return_value=listed) as history,
            patch.object(strategies, "revert_version", return_value=restored) as revert,
        ):
            history_response = self.client.get("/strategies/3/versions")
            revert_response = self.client.post("/strategies/3/versions/8/revert")
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json(), listed)
        history.assert_called_once_with(4, 3)
        self.assertEqual(revert_response.status_code, 200)
        self.assertEqual(revert_response.json()["name"], "Earlier")
        revert.assert_called_once_with(4, 3, 8)

    def test_versions_hide_a_missing_strategy_and_reject_a_non_owner(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_versions", side_effect=strategies.StrategyNotFound()),
        ):
            missing = self.client.get("/strategies/3/versions")
        self.assertEqual(missing.status_code, 404)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "revert_version", side_effect=strategies.StrategyForbidden()),
        ):
            forbidden = self.client.post("/strategies/3/versions/8/revert")
        self.assertEqual(forbidden.status_code, 403)

    def test_database_outage_is_a_service_error(self) -> None:
        _sign_in(self.client)
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(strategies, "list_strategies", side_effect=RuntimeError("missing env")),
        ):
            response = self.client.get("/strategies")
        self.assertEqual(response.status_code, 503)


class _Result:
    def __init__(self, row: tuple | list | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        if isinstance(self._row, list):
            return self._row[0] if self._row else None
        return self._row

    def fetchall(self) -> list:
        if self._row is None:
            return []
        if isinstance(self._row, list):
            return self._row
        return [self._row]


class _Conn:
    def __init__(self, rows: list[tuple | None]) -> None:
        self._rows = list(rows)
        self.statements: list[tuple[str, object]] = []
        self.closed = False
        self.committed = False

    def transaction(self) -> "_Conn":
        return self

    def __enter__(self) -> "_Conn":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> _Result:
        self.statements.append((" ".join(sql.split()), params))
        row = self._rows.pop(0) if self._rows else None
        return _Result(row)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _saved_row(
    strategy_id: int = 8,
    user_id: int = 4,
    name: str = "Trend",
    visibility: str = "private",
    document: dict | None = None,
    ir: dict | None = None,
) -> tuple:
    moment = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    return (
        strategy_id,
        user_id,
        name,
        visibility,
        document if document is not None else DOCUMENT,
        ir,
        moment,
        moment,
    )


class _SchemaConn:
    """Records DDL and returns a row only for the strategy insert."""

    def __init__(self, row: tuple) -> None:
        self._row = row
        self.statements: list[tuple[str, object]] = []
        self.closed = False

    def transaction(self) -> "_SchemaConn":
        return self

    def __enter__(self) -> "_SchemaConn":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> _Result:
        folded = " ".join(sql.split())
        self.statements.append((folded, params))
        if folded.startswith("INSERT INTO strategies"):
            return _Result(self._row)
        if "FROM pg_constraint" in folded:
            return _Result((1,))
        return _Result(None)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class SaveStrategyDbTest(unittest.TestCase):
    def setUp(self) -> None:
        strategies._storage_ready = True

    def test_save_creates_the_version_table_before_inserting(self) -> None:
        import helpers.discussions as discussions

        strategies._storage_ready = False
        discussions._schema_ready = False
        conn = _SchemaConn(_saved_row())
        try:
            with patch.object(strategies, "_connect", return_value=conn):
                result = strategies.create_strategy(4, "Trend", DOCUMENT, None)
        finally:
            strategies._storage_ready = True
            discussions._schema_ready = True
        self.assertEqual(result["id"], 8)
        folded = [sql for sql, _params in conn.statements]
        create_strategies = folded.index(
            next(sql for sql in folded if "CREATE TABLE IF NOT EXISTS strategies" in sql)
        )
        insert_strategies = folded.index(
            next(sql for sql in folded if sql.startswith("INSERT INTO strategies"))
        )
        create_versions = folded.index(
            next(sql for sql in folded if "CREATE TABLE IF NOT EXISTS strategy_versions" in sql)
        )
        insert_versions = folded.index(
            next(sql for sql in folded if sql.startswith("INSERT INTO strategy_versions"))
        )
        self.assertLess(create_strategies, insert_strategies)
        self.assertLess(create_versions, insert_versions)
        self.assertTrue(conn.closed)

    def test_create_inserts_the_caller_and_returns_a_summary(self) -> None:
        conn = _Conn([_saved_row(visibility="public", ir=IR)])
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.create_strategy(4, " Trend ", DOCUMENT, IR, "public")
        self.assertEqual(
            result,
            {
                "id": 8,
                "name": "Trend",
                "visibility": "public",
                "updated_at": "2026-09-26T12:00:00+00:00",
            },
        )
        sql, params = conn.statements[0]
        self.assertIn("INSERT INTO strategies (user_id, name, visibility, document, ir)", sql)
        version_sql, version_params = conn.statements[1]
        self.assertIn("INSERT INTO strategy_versions", version_sql)
        self.assertIn("'save'", version_sql)
        self.assertEqual(version_params[0], 8)
        self.assertEqual(params[0], 4)
        self.assertEqual(params[1], "Trend")
        self.assertEqual(params[2], "public")
        self.assertIsInstance(params[3], Jsonb)
        self.assertEqual(params[3].obj, DOCUMENT)
        self.assertIsInstance(params[4], Jsonb)
        self.assertEqual(params[4].obj, IR)
        self.assertTrue(conn.committed)
        self.assertTrue(conn.closed)

    def test_create_defaults_to_private_without_touching_a_client_user_id(self) -> None:
        conn = _Conn([_saved_row()])
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.create_strategy(4, "Trend", {"user_id": 99, "nodes": []})
        self.assertEqual(result["visibility"], "private")
        self.assertNotIn("user_id", result)
        self.assertNotIn("document", result)
        _sql, params = conn.statements[0]
        self.assertEqual(params[0], 4)
        self.assertEqual(params[2], "private")
        self.assertIsNone(params[4])

    def test_update_sets_updated_at_for_the_owner_and_returns_a_summary(self) -> None:
        current = _saved_row(strategy_id=3)
        saved = _saved_row(strategy_id=3, name="Breakout", visibility="public")
        conn = _Conn([current, saved])
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.update_strategy(4, 3, name="Breakout", visibility="public")
        self.assertEqual(
            result,
            {
                "id": 3,
                "name": "Breakout",
                "visibility": "public",
                "updated_at": "2026-09-26T12:00:00+00:00",
            },
        )
        sql, params = conn.statements[1]
        self.assertIn("updated_at = now()", sql)
        self.assertIn("WHERE id = %s AND user_id = %s", sql)
        self.assertEqual(params[0], "Breakout")
        self.assertEqual(params[1], "public")
        self.assertEqual(params[-2:], [3, 4])
        self.assertTrue(conn.committed)
        self.assertTrue(conn.closed)

    def test_update_rejects_a_non_owner_before_writing(self) -> None:
        conn = _Conn([_saved_row(strategy_id=3, user_id=9, visibility="public")])
        with patch.object(strategies, "_connect", return_value=conn):
            with self.assertRaises(strategies.StrategyForbidden):
                strategies.update_strategy(4, 3, name="Nope")
        self.assertEqual(len(conn.statements), 1)
        self.assertIn("SELECT", conn.statements[0][0])

    def test_update_is_not_found_when_the_row_is_missing(self) -> None:
        conn = _Conn([None])
        with patch.object(strategies, "_connect", return_value=conn):
            with self.assertRaises(strategies.StrategyNotFound):
                strategies.update_strategy(4, 99, name="Nope")
        self.assertEqual(len(conn.statements), 1)

    def test_update_with_a_document_records_a_save_version(self) -> None:
        current = _saved_row(strategy_id=3)
        saved = _saved_row(strategy_id=3, document={"name": "Breakout", "nodes": [1]})
        conn = _Conn([current, saved])
        with patch.object(strategies, "_connect", return_value=conn):
            strategies.update_strategy(4, 3, document={"name": "Breakout", "nodes": [1]})
        version_sql, version_params = conn.statements[2]
        self.assertIn("INSERT INTO strategy_versions", version_sql)
        self.assertIn("'save'", version_sql)
        self.assertEqual(version_params[1].obj["name"], "Breakout")

    def test_name_only_update_does_not_record_a_version(self) -> None:
        conn = _Conn([_saved_row(strategy_id=3), _saved_row(strategy_id=3, name="Breakout")])
        with patch.object(strategies, "_connect", return_value=conn):
            strategies.update_strategy(4, 3, name="Breakout")
        self.assertEqual(len(conn.statements), 2)

    def test_copy_records_a_save_version(self) -> None:
        conn = _Conn([_saved_row(), (12,)])
        with patch.object(strategies, "_connect", return_value=conn):
            new_id = strategies.copy_strategy(4, 8)
        self.assertEqual(new_id, 12)
        version_sql, version_params = conn.statements[2]
        self.assertIn("'save'", version_sql)
        self.assertEqual(version_params[0], 12)

    def test_list_versions_returns_saves_newest_first_for_the_owner(self) -> None:
        moment = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        older = datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)
        conn = _Conn(
            [
                _saved_row(strategy_id=3, name="Trend"),
                [
                    (9, {"name": "  Later  "}, moment),
                    (8, {"nodes": []}, older),
                ],
            ]
        )
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.list_versions(4, 3)
        self.assertEqual(
            result,
            [
                {"id": 9, "name": "Later", "created_at": moment.isoformat()},
                {"id": 8, "name": "Trend", "created_at": older.isoformat()},
            ],
        )
        self.assertIn("kind = 'save'", conn.statements[1][0])

    def test_list_versions_rejects_a_non_owner(self) -> None:
        conn = _Conn([_saved_row(strategy_id=3, user_id=9, visibility="public")])
        with patch.object(strategies, "_connect", return_value=conn):
            with self.assertRaises(strategies.StrategyForbidden):
                strategies.list_versions(4, 3)
        self.assertEqual(len(conn.statements), 1)

    def test_revert_copies_the_saved_document_and_records_it_again(self) -> None:
        earlier = {"name": "Earlier", "nodes": [1]}
        conn = _Conn(
            [
                _saved_row(strategy_id=3),
                (earlier, IR),
                _saved_row(strategy_id=3, name="Earlier", document=earlier, ir=IR),
            ]
        )
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.revert_version(4, 3, 8)
        self.assertEqual(result["name"], "Earlier")
        self.assertEqual(result["document"], earlier)
        self.assertEqual(result["ir"], IR)
        update_sql, update_params = conn.statements[2]
        self.assertIn("UPDATE strategies", update_sql)
        self.assertEqual(update_params[0], "Earlier")
        version_sql, version_params = conn.statements[3]
        self.assertIn("INSERT INTO strategy_versions", version_sql)
        self.assertIn("'save'", version_sql)
        self.assertTrue(conn.committed)

    def test_revert_is_not_found_when_the_version_is_missing(self) -> None:
        conn = _Conn([_saved_row(strategy_id=3), None])
        with patch.object(strategies, "_connect", return_value=conn):
            with self.assertRaises(strategies.StrategyNotFound):
                strategies.revert_version(4, 3, 99)
        self.assertEqual(len(conn.statements), 2)

    def test_update_requires_a_field(self) -> None:
        conn = _Conn([_saved_row(strategy_id=3)])
        with patch.object(strategies, "_connect", return_value=conn):
            with self.assertRaises(ValueError):
                strategies.update_strategy(4, 3)
        self.assertEqual(len(conn.statements), 1)


class _DurableTx:
    """Same rule as psycopg: only an idle connection commits on the way out."""

    def __init__(self, conn: "_DurableConn") -> None:
        self.conn = conn
        self.outer = False

    def __enter__(self) -> "_DurableTx":
        self.outer = self.conn.status == "idle"
        if self.outer:
            self.conn.status = "intrans"
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is not None:
            self.conn.rollback()
            return False
        if self.outer:
            self.conn.commit()
        return False


class _DurableConn:
    """connect() leaves SET TIME ZONE uncommitted. close() drops that work."""

    def __init__(self, row: tuple) -> None:
        self._row = row
        self.status = "intrans"
        self.pending: tuple | None = None
        self.durable: tuple | None = None
        self.closed = False

    def commit(self) -> None:
        if self.pending is not None:
            self.durable = self.pending
            self.pending = None
        self.status = "idle"

    def rollback(self) -> None:
        self.pending = None
        self.status = "idle"

    def transaction(self) -> _DurableTx:
        return _DurableTx(self)

    def execute(self, sql: str, params: object = None) -> _Result:
        if self.status == "idle":
            self.status = "intrans"
        folded = " ".join(sql.split())
        if folded.startswith("INSERT") or folded.startswith("UPDATE"):
            self.pending = self._row
        return _Result(self._row)

    def close(self) -> None:
        if self.status == "intrans":
            self.rollback()
        self.closed = True


class StrategySurvivesCloseTest(unittest.TestCase):
    def setUp(self) -> None:
        strategies._storage_ready = True

    def test_create_is_still_stored_after_close(self) -> None:
        conn = _DurableConn(_saved_row())
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.create_strategy(4, "Trend", DOCUMENT, None)
        self.assertEqual(result["id"], 8)
        self.assertEqual(conn.durable, _saved_row())
        self.assertTrue(conn.closed)
        self.assertEqual(conn.status, "idle")

    def test_update_is_still_stored_after_close(self) -> None:
        saved = _saved_row(strategy_id=3, name="Breakout")
        conn = _DurableConn(saved)
        with patch.object(strategies, "_connect", return_value=conn):
            result = strategies.update_strategy(4, 3, name="Breakout")
        self.assertEqual(result["name"], "Breakout")
        self.assertEqual(conn.durable, saved)
        self.assertTrue(conn.closed)

    def test_copy_is_still_stored_after_close(self) -> None:
        conn = _DurableConn(_saved_row(strategy_id=12))
        with patch.object(strategies, "_connect", return_value=conn):
            new_id = strategies.copy_strategy(4, 8)
        self.assertEqual(new_id, 12)
        self.assertEqual(conn.durable[0], 12)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
