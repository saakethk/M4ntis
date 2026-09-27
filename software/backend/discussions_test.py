"""Posting a strategy publishes it only for the owner."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import helpers.auth as auth
import helpers.discussions as discussions
import main
from helpers.auth import User

OWNER = User(4, "owner@example.com")
OTHER = User(9, "other@example.com")


def _sign_in(client: TestClient) -> None:
    client.cookies.set("session", "raw-token")


class _Result:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row

    def fetchall(self) -> list:
        if isinstance(self._row, list):
            return self._row
        if self._row is None:
            return []
        return [self._row]


class _Conn:
    def __init__(self, rows: list[tuple | None]) -> None:
        self._rows = list(rows)
        self.statements: list[tuple[str, object]] = []
        self.closed = False

    def commit(self) -> None:
        return None

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

    def close(self) -> None:
        self.closed = True


class PostPublishesStrategyTest(unittest.TestCase):
    def setUp(self) -> None:
        discussions._schema_ready = True
        self.client = TestClient(main.app)
        _sign_in(self.client)

    def test_owner_posting_a_private_strategy_makes_it_public(self) -> None:
        conn = _Conn([(8, 4, "private"), (8,), (21,)])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.post(
                "/discussions",
                json={"body": "Look at this", "strategy_id": 8},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {"id": 21, "strategy_id": 8, "strategy_made_public": True},
        )
        self.assertIn("UPDATE strategies", conn.statements[1][0])
        self.assertIn("visibility = 'public'", conn.statements[1][0])
        self.assertIn("updated_at = now()", conn.statements[1][0])
        self.assertEqual(conn.statements[1][1], (8, 4))
        self.assertIn("INSERT INTO discussion_posts", conn.statements[2][0])
        self.assertTrue(conn.closed)

    def test_posting_an_already_public_strategy_leaves_visibility(self) -> None:
        conn = _Conn([(8, 4, "public"), (22,)])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.post(
                "/discussions",
                json={"body": "Already shared", "strategy_id": 8},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {"id": 22, "strategy_id": 8, "strategy_made_public": False},
        )
        self.assertEqual(len(conn.statements), 2)
        self.assertNotIn("UPDATE", conn.statements[0][0])
        self.assertNotIn("UPDATE", conn.statements[1][0])

    def test_non_owner_posting_a_private_strategy_is_rejected(self) -> None:
        conn = _Conn([(8, 4, "private")])
        with (
            patch.object(auth, "user_from_token", return_value=OTHER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.post(
                "/discussions",
                json={"body": "Not mine", "strategy_id": 8},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(conn.statements), 1)
        self.assertIn("SELECT", conn.statements[0][0])
        self.assertNotIn("UPDATE", conn.statements[0][0])
        self.assertTrue(conn.closed)

    def test_reply_to_a_missing_post_is_404(self) -> None:
        conn = _Conn([None])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.post(
                "/discussions",
                json={"body": "A reply", "parent_id": 99},
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("discussion_posts", conn.statements[0][0])

    def test_list_returns_posts_for_the_signed_in_user(self) -> None:
        from datetime import datetime, timezone

        created = datetime(2024, 1, 2, tzinfo=timezone.utc)
        conn = _Conn(
            [[(3, 4, "owner@example.com", "Hello", 8, "Mean reversion", None, 2, created, True)]]
        )
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.get("/discussions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["body"], "Hello")
        self.assertEqual(response.json()[0]["strategy_id"], 8)
        self.assertEqual(response.json()[0]["strategy_name"], "Mean reversion")
        self.assertEqual(response.json()[0]["likes_count"], 2)
        self.assertTrue(response.json()[0]["liked"])
        self.assertEqual(conn.statements[0][1], (4,))
        listed = conn.statements[0][0]
        self.assertIn("LEFT JOIN strategies", listed)
        self.assertNotIn("WHERE p.user_id", listed)
        self.assertIn("ORDER BY p.created_at DESC, p.id DESC", listed)

    def test_first_request_creates_the_tiger_tables(self) -> None:
        discussions._schema_ready = False
        conn = _Conn([])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=conn),
        ):
            response = self.client.get("/discussions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        created = " ".join(sql for sql, _params in conn.statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS discussion_posts", created)
        self.assertIn("CREATE TABLE IF NOT EXISTS discussion_likes", created)
        self.assertTrue(discussions._schema_ready)
        self.assertIn("SELECT", conn.statements[-1][0])

    def test_like_toggles_and_missing_post_is_404(self) -> None:
        missing = _Conn([None])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=missing),
        ):
            response = self.client.post("/discussions/9/like")
        self.assertEqual(response.status_code, 404)

        liked = _Conn([(0,), None, None, (1,)])
        with (
            patch.object(auth, "user_from_token", return_value=OWNER),
            patch.object(discussions, "_connect", return_value=liked),
        ):
            response = self.client.post("/discussions/9/like")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": 9, "likes_count": 1, "liked": True})
        self.assertIn("INSERT INTO discussion_likes", liked.statements[2][0])


if __name__ == "__main__":
    unittest.main()
