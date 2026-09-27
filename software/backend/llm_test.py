"""Assistant route tests. The model is faked; nothing is sent to a provider."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from helpers.ai_agent import AIConfigError, AIProviderError, ChatResponse
from helpers.auth import User
from helpers.llm import ask


PROGRAM = {
    "resolution": "1m",
    "symbol": "AAPL",
    "fast": 8,
    "slow": 20,
    "quantity": 4,
}

CROSSOVER = (
    "Every 1 minute, compare the 8-bar average with the 20-bar average and buy 4 AAPL when it is higher.\n\n"
    '```json\n{"program": {"resolution": "1m", "symbol": "aapl", "fast": 8, "slow": 20, "quantity": 4}}\n```'
)


class AskTest(unittest.TestCase):
    def test_explanation_has_no_program(self) -> None:
        body = ask("what is a tick?", complete=lambda prompt: "A tick is one bar at the Start resolution.")
        self.assertEqual(body["dummy"], False)
        self.assertEqual(body["reply"], "A tick is one bar at the Start resolution.")
        self.assertIsNone(body["program"])

    def test_crossover_reply_keeps_the_prose_and_program(self) -> None:
        seen: list[str] = []

        def complete(prompt: str) -> str:
            seen.append(prompt)
            return CROSSOVER

        body = ask("  buy Apple when the fast average wins  ", complete=complete)
        self.assertEqual(seen, ["buy Apple when the fast average wins"])
        self.assertEqual(body["program"], PROGRAM)
        self.assertIn("buy 4 AAPL", str(body["reply"]))
        self.assertNotIn("```", str(body["reply"]))

    def test_invalid_program_is_dropped(self) -> None:
        raw = 'Use a coarser resolution.\n```json\n{"program": {"resolution": "1w", "symbol": "AAPL", "fast": 50, "slow": 10, "quantity": 4}}\n```'
        body = ask("fifty day average", complete=lambda prompt: raw)
        self.assertIsNone(body["program"])
        self.assertEqual(body["reply"], "Use a coarser resolution.")

    def test_json_reply_object_is_accepted(self) -> None:
        raw = '{"reply": "Buy when the fast average is above the slow one.", "program": {"resolution": "5m", "symbol": "MSFT", "fast": 10.0, "slow": 30, "quantity": 10}}'
        body = ask("sma crossover on microsoft", complete=lambda prompt: raw)
        self.assertEqual(body["reply"], "Buy when the fast average is above the slow one.")
        self.assertEqual(body["program"]["symbol"], "MSFT")
        self.assertEqual(body["program"]["fast"], 10)

    def test_blank_prompt_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ask("   ", complete=lambda prompt: "unused")

    def test_empty_model_text_is_an_error(self) -> None:
        with self.assertRaises(AIProviderError):
            ask("help", complete=lambda prompt: "  ")


class _FakeAgent:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict = {}

    def __enter__(self) -> "_FakeAgent":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def chat(self, messages: str, **kwargs: object) -> ChatResponse:
        self.kwargs = {"messages": messages, **kwargs}
        return ChatResponse(text=self.text, provider="openai", model="m")


class LlmRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_ask_requires_a_session(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=None):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 401)

    def test_ask_returns_the_model_reply(self) -> None:
        agent = _FakeAgent(CROSSOVER)
        with (
            patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", return_value=agent),
        ):
            response = self.client.post("/llm", json={"prompt": "help me buy AAPL"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["dummy"])
        self.assertEqual(body["program"], PROGRAM)
        self.assertIn("buy 4 AAPL", body["reply"])
        self.assertIn("Canvas program", agent.kwargs["system_prompt"])
        self.assertEqual(agent.kwargs["temperature"], 0.2)

    def test_empty_prompt_is_400(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Prompt is required")

    def test_extra_fields_are_rejected(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "help", "model": "gpt"})
        self.assertEqual(response.status_code, 422)

    def test_missing_provider_is_503(self) -> None:
        with (
            patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", side_effect=AIConfigError("set AI_PROVIDER")),
        ):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Assistant is not configured")

    def test_provider_failure_is_502(self) -> None:
        with (
            patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", side_effect=AIProviderError("openai", "bad key", 401)),
        ):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Assistant is unavailable")
