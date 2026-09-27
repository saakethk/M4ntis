"""Dummy assistant tests. No database and no model."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from helpers.auth import User
from helpers.llm import HELP, dummy_reply


class DummyReplyTest(unittest.TestCase):
    def test_general_prompt_explains_start_and_get_ticker(self) -> None:
        body = dummy_reply("  build a mean reversion strategy  ")
        self.assertEqual(body["dummy"], True)
        self.assertEqual(body["reply"], HELP)
        self.assertIsNone(body["program"])
        self.assertNotIn("mean reversion", str(body["reply"]))

    def test_trade_prompt_builds_a_get_ticker_program(self) -> None:
        body = dummy_reply("every 1 minute buy 4 shares of Apple when the 8 average beats 20")
        self.assertEqual(body["dummy"], True)
        self.assertEqual(
            body["program"],
            {"resolution": "1m", "symbol": "AAPL", "fast": 8, "slow": 20, "quantity": 4},
        )
        self.assertIn("Get ticker AAPL", str(body["reply"]))

    def test_blank_prompt_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            dummy_reply("   ")


class LlmRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_ask_requires_a_session(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=None):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 401)

    def test_ask_returns_the_dummy_reply(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "help me buy AAPL"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["dummy"])
        self.assertEqual(body["program"]["symbol"], "AAPL")
        self.assertIn("Get ticker AAPL", body["reply"])

    def test_empty_prompt_is_400(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Prompt is required")

    def test_extra_fields_are_rejected(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "help", "model": "gpt"})
        self.assertEqual(response.status_code, 422)
