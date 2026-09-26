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


class _Conn:
    def __init__(self, rows: list[tuple | None]) -> None:
        self._rows = list(rows)
        self.statements: list[tuple[str, object]] = []
        self.closed = False

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


if __name__ == "__main__":
    unittest.main()
