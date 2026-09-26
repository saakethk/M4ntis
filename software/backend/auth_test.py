"""Auth tests that do not require Tiger Data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import helpers.auth as auth
import main
from helpers.auth import User


class PasswordTest(unittest.TestCase):
    def test_hash_round_trip(self) -> None:
        stored = auth.hash_password("correct horse")
        self.assertTrue(auth.verify_password("correct horse", stored))
        self.assertFalse(auth.verify_password("wrong horse", stored))
        self.assertNotIn("correct horse", stored)

    def test_short_password_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            auth.hash_password("short")

    def test_email_is_normalized(self) -> None:
        self.assertEqual(auth.normalize_email("  Person@Example.com "), "person@example.com")
        with self.assertRaises(ValueError):
            auth.normalize_email("not-an-email")


class AuthRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_register_sets_a_session_cookie(self) -> None:
        user = User(1, "person@example.com")
        with patch.object(auth, "register_user", return_value=(user, "raw-token")):
            response = self.client.post(
                "/auth/register",
                json={"email": "person@example.com", "password": "correct horse"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": 1, "email": "person@example.com"})
        self.assertEqual(response.cookies.get("session"), "raw-token")

    def test_login_rejects_bad_credentials(self) -> None:
        with patch.object(auth, "login", side_effect=auth.InvalidCredentials()):
            response = self.client.post(
                "/auth/login",
                json={"email": "person@example.com", "password": "correct horse"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(response.cookies.get("session"))

    def test_login_cookie_authenticates_the_next_me(self) -> None:
        user = User(7, "person@example.com")

        def lookup(token: str) -> User | None:
            if token == "raw-token":
                return user
            return None

        with patch.object(auth, "login", return_value=(user, "raw-token")):
            logged_in = self.client.post(
                "/auth/login",
                json={"email": "person@example.com", "password": "correct horse"},
            )
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(logged_in.json(), {"id": 7, "email": "person@example.com"})
        self.assertEqual(logged_in.cookies.get("session"), "raw-token")
        header = logged_in.headers["set-cookie"]
        lowered = header.lower()
        self.assertIn("httponly", lowered)
        self.assertIn("path=/", lowered)
        self.assertIn("samesite=lax", lowered)
        self.assertNotIn("secure", lowered)
        self.assertNotIn("domain=", lowered)
        self.assertEqual(self.client.cookies.get("session"), "raw-token")

        with patch.object(auth, "user_from_token", side_effect=lookup) as seen:
            me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json(), {"id": 7, "email": "person@example.com"})
        seen.assert_called_once_with("raw-token")

        self.client.cookies.clear()
        with patch.object(auth, "user_from_token", side_effect=lookup) as seen_again:
            missing = self.client.get("/auth/me")
        self.assertEqual(missing.status_code, 401)
        seen_again.assert_called_once_with("")

    def test_me_requires_a_session(self) -> None:
        with patch.object(auth, "user_from_token", return_value=None):
            missing = self.client.get("/auth/me")
        self.assertEqual(missing.status_code, 401)

        user = User(1, "person@example.com")
        self.client.cookies.set("session", "raw-token")
        with patch.object(auth, "user_from_token", return_value=user):
            found = self.client.get("/auth/me")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["email"], "person@example.com")


if __name__ == "__main__":
    unittest.main()
