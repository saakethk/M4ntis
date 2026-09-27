"""Assistant route tests. The model is faked; nothing is sent to a provider."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from helpers.ai_agent import AIConfigError, AIProviderError, ChatResponse
from helpers.canvas import normalize_graph
from helpers.llm import ASSISTANT_MODELS, ask, resolve_assistant_model


BANDS = {
    "nodes": [
        {"id": "start", "type": "start", "params": {"resolution": "15m"}},
        {"id": "t0", "type": "get_ticker", "params": {"symbol": "nvda"}},
        {"id": "bands", "type": "mean_reversion_bands", "params": {"n": 20, "k": 2}},
        {"id": "low", "type": "if", "params": {"operator": "<="}},
        {"id": "buy", "type": "buy", "params": {"quantity": 5}},
    ],
    "edges": [
        {"source": "start", "sourceHandle": "exec:out", "target": "low", "targetHandle": "exec:in"},
        {"source": "bands", "sourceHandle": "data:lower", "target": "low", "targetHandle": "data:a"},
        {"from": "t0", "sourceHandle": "data:out", "to": "low", "targetHandle": "data:b"},
        {"source": "low", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"},
    ],
}

REPLY = (
    "Buy 5 NVDA when price is at or below the lower band.\n\n"
    '```json\n{"graph": {"nodes": ['
    '{"id": "start", "type": "start", "params": {"resolution": "15m"}},'
    '{"id": "t0", "type": "get_ticker", "params": {"symbol": "nvda"}},'
    '{"id": "bands", "type": "mean_reversion_bands", "params": {"n": 20, "k": 2}},'
    '{"id": "low", "type": "if", "params": {"operator": "<="}},'
    '{"id": "buy", "type": "buy", "params": {"quantity": 5}}'
    '], "edges": ['
    '{"source": "start", "sourceHandle": "exec:out", "target": "low", "targetHandle": "exec:in"},'
    '{"source": "bands", "sourceHandle": "data:lower", "target": "low", "targetHandle": "data:a"},'
    '{"source": "t0", "sourceHandle": "data:out", "target": "low", "targetHandle": "data:b"},'
    '{"source": "low", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"}'
    ']}}\n```'
)


class AskTest(unittest.TestCase):
    def test_explanation_has_no_graph(self) -> None:
        body = ask("what is a tick?", complete=lambda prompt: "A tick is one bar at the Start resolution.")
        self.assertEqual(body["dummy"], False)
        self.assertEqual(body["reply"], "A tick is one bar at the Start resolution.")
        self.assertIsNone(body["graph"])

    def test_graph_reply_keeps_the_prose_and_blocks(self) -> None:
        seen: list[str] = []

        def complete(prompt: str) -> str:
            seen.append(prompt)
            return REPLY

        canvas = {"nodes": [{"id": "start", "type": "start", "params": {"resolution": "5m"}}], "edges": []}
        body = ask("  buy when price touches the lower band  ", canvas, complete=complete)
        self.assertIn("Current canvas:", seen[0])
        self.assertIn('"resolution":"5m"', seen[0])
        self.assertIn("User request:\nbuy when price touches the lower band", seen[0])
        graph = body["graph"]
        self.assertIsInstance(graph, dict)
        self.assertEqual(
            [node["type"] for node in graph["nodes"]],  # type: ignore[index]
            ["start", "get_ticker", "mean_reversion_bands", "if", "buy"],
        )
        ticker = graph["nodes"][1]  # type: ignore[index]
        self.assertEqual(ticker["params"]["symbol"], "NVDA")
        self.assertEqual(ticker["params"]["buffer"], 0)
        self.assertIn("lower band", str(body["reply"]))
        self.assertNotIn("```", str(body["reply"]))
        self.assertEqual(len(graph["edges"]), 4)  # type: ignore[arg-type]

    def test_invalid_graph_is_dropped(self) -> None:
        raw = 'Use a coarser resolution.\n```json\n{"graph": {"nodes": [{"id": "start", "type": "start", "params": {}}, {"id": "a", "type": "log", "params": {}}], "edges": []}}\n```'
        body = ask("add a log", complete=lambda prompt: raw)
        self.assertIsNone(body["graph"])
        self.assertEqual(body["reply"], "Use a coarser resolution.")

    def test_cycle_is_dropped(self) -> None:
        raw = (
            '```json\n{"graph": {"nodes": ['
            '{"id": "start", "type": "start", "params": {}},'
            '{"id": "a", "type": "set_var", "params": {"slot": "VAR1"}},'
            '{"id": "b", "type": "set_var", "params": {"slot": "VAR2"}}'
            '], "edges": ['
            '{"source": "start", "sourceHandle": "exec:out", "target": "a", "targetHandle": "exec:in"},'
            '{"source": "a", "sourceHandle": "exec:out", "target": "b", "targetHandle": "exec:in"},'
            '{"source": "b", "sourceHandle": "exec:out", "target": "a", "targetHandle": "exec:in"}'
            ']}}\n```'
        )
        body = ask("loop the sets", complete=lambda prompt: raw)
        self.assertIsNone(body["graph"])

    def test_blank_prompt_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ask("   ", complete=lambda prompt: "unused")

    def test_bad_canvas_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            ask("help", {"nodes": [{"id": "x", "type": "nope", "params": {}}], "edges": []})
        self.assertEqual(str(caught.exception), "Canvas graph is not valid")

    def test_empty_model_text_is_an_error(self) -> None:
        with self.assertRaises(AIProviderError):
            ask("help", complete=lambda prompt: "  ")

    def test_omitted_model_keeps_the_environment_default(self) -> None:
        self.assertEqual(resolve_assistant_model(None, None), (None, None))
        self.assertEqual(resolve_assistant_model("  ", ""), (None, None))

    def test_known_models_resolve(self) -> None:
        self.assertEqual(
            resolve_assistant_model("gemini", "gemini-2.5-pro"),
            ("gemini", "gemini-2.5-pro"),
        )
        self.assertEqual(
            resolve_assistant_model(None, "muse-spark-1.1"),
            ("meta", "muse-spark-1.1"),
        )
        self.assertEqual(resolve_assistant_model("meta", None), ("meta", "muse-spark-1.3"))
        self.assertEqual(
            resolve_assistant_model(None, "muse-spark-1.2"),
            ("meta", "muse-spark-1.2"),
        )
        self.assertEqual(
            ASSISTANT_MODELS["meta"],
            (
                "muse-spark-1.3",
                "muse-spark-1.3-contributor",
                "muse-spark-1.2",
                "muse-spark-1.2-contributor",
                "muse-spark-1.1",
            ),
        )
        self.assertEqual(ASSISTANT_MODELS["gemini"][0], "gemini-2.5-flash")

    def test_unknown_provider_and_model_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as unknown_provider:
            ask("help", provider="cursor", model="gpt", complete=lambda prompt: "unused")
        self.assertIn("Unknown provider", str(unknown_provider.exception))
        called: list[str] = []
        with self.assertRaises(ValueError) as unknown_model:
            ask(
                "help",
                provider="gemini",
                model="gpt",
                complete=lambda prompt: called.append(prompt) or "unused",
            )
        self.assertIn("Unknown model", str(unknown_model.exception))
        self.assertEqual(called, [])
        with self.assertRaises(ValueError):
            ask("help", provider="gemini", model="muse-spark-1.3", complete=lambda prompt: "unused")


class NormalizeGraphTest(unittest.TestCase):
    def test_mean_reversion_graph_fills_defaults(self) -> None:
        graph = normalize_graph(BANDS)
        buy = next(node for node in graph["nodes"] if node["type"] == "buy")
        self.assertEqual(buy["params"]["buffer"], 0)
        self.assertEqual(buy["params"]["quantity"], 5)
        bands = next(node for node in graph["nodes"] if node["type"] == "mean_reversion_bands")
        self.assertEqual(bands["params"]["buffer"], 0)
        self.assertEqual(graph["edges"][2]["source"], "t0")


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

    def test_ask_returns_the_model_graph(self) -> None:
        agent = _FakeAgent(REPLY)
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", return_value=agent) as from_env,
        ):
            response = self.client.post(
                "/llm",
                json={
                    "prompt": "add a lower band buy",
                    "graph": {"nodes": [{"id": "start", "type": "start", "params": {}}], "edges": []},
                },
            )
        from_env.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["dummy"])
        self.assertEqual(body["graph"]["nodes"][1]["params"]["symbol"], "NVDA")
        self.assertIn("lower band", body["reply"])
        self.assertIn("Canvas graph", agent.kwargs["system_prompt"])
        self.assertIn("mean_reversion_bands", agent.kwargs["system_prompt"])
        self.assertEqual(agent.kwargs["max_tokens"], 4096)
        self.assertIn("Current canvas:", agent.kwargs["messages"])

    def test_empty_prompt_is_400(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Prompt is required")

    def test_invalid_canvas_is_400(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "graph": {"nodes": [{"id": "x", "type": "log", "params": {}}], "edges": []}},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Canvas graph is not valid")

    def test_editor_node_fields_are_accepted(self) -> None:
        agent = _FakeAgent("A tick is one bar.")
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", return_value=agent),
        ):
            response = self.client.post(
                "/llm",
                json={
                    "prompt": "what is a tick?",
                    "graph": {
                        "nodes": [
                            {
                                "id": "start",
                                "type": "start",
                                "position": {"x": 0, "y": -200},
                                "measured": {"width": 180, "height": 40},
                                "data": {"params": {"resolution": "15m", "startingBalance": 50000}},
                                "selected": True,
                            }
                        ],
                        "edges": [
                            {
                                "id": "e1",
                                "source": "start",
                                "sourceHandle": None,
                                "target": "buy",
                                "targetHandle": "exec:in",
                                "data": {"kind": "exec"},
                                "className": "edge-exec",
                            }
                        ],
                    },
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('"resolution":"15m"', agent.kwargs["messages"])
        self.assertIn('"startingBalance":50000', agent.kwargs["messages"])
        self.assertNotIn("position", agent.kwargs["messages"])

    def test_extra_fields_are_rejected(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")):
            response = self.client.post("/llm", json={"prompt": "help", "temperature": 0})
        self.assertEqual(response.status_code, 422)

    def test_provider_and_model_are_not_extra_inputs(self) -> None:
        agent = _FakeAgent("A tick is one bar.")
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", return_value=agent),
        ):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "provider": "gemini", "model": "gemini-2.5-flash"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("Extra inputs are not permitted", response.text)

    def test_selected_model_is_passed_to_the_agent(self) -> None:
        agent = _FakeAgent("A tick is one bar.")
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", return_value=agent) as from_env,
        ):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "provider": "meta", "model": "muse-spark-1.1"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        from_env.assert_called_once_with(provider="meta", model="muse-spark-1.1")

    def test_unknown_model_is_400(self) -> None:
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env") as from_env,
        ):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "provider": "gemini", "model": "gpt"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown model", response.json()["detail"])
        from_env.assert_not_called()

    def test_unknown_provider_is_400(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "provider": "cursor", "model": "gemini-2.5-flash"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown provider", response.json()["detail"])

    def test_missing_selected_provider_key_is_503(self) -> None:
        env = {
            "AI_PROVIDER": "gemini",
            "AI_MODEL": "gemini-2.5-flash",
            "GEMINI_API_KEY": "present",
            "META_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "AI_API_KEY": "",
        }
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch("helpers.ai_agent._load_repo_env"),
            patch.dict("os.environ", env),
        ):
            response = self.client.post(
                "/llm",
                json={"prompt": "help", "provider": "meta", "model": "muse-spark-1.3"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("META_API_KEY", response.json()["detail"])
        self.assertIn(".env", response.json()["detail"])

    def test_missing_provider_is_503(self) -> None:
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", side_effect=AIConfigError("set AI_PROVIDER")),
        ):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "set AI_PROVIDER")

    def test_provider_failure_is_502(self) -> None:
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(main.llm.AIAgent, "from_env", side_effect=AIProviderError("openai", "bad key", 401)),
        ):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Assistant is unavailable: openai: bad key (HTTP 401)")

    def test_provider_failure_does_not_echo_an_api_key(self) -> None:
        leaked = "AIzaSyDUMMYKEYVALUE1234567890"
        with (
            patch.object(main.auth, "user_from_token", return_value=main.auth.User(4, "a@b.com")),
            patch.object(
                main.llm.AIAgent,
                "from_env",
                side_effect=AIProviderError("gemini", f"rejected bearer {leaked}", 400),
            ),
        ):
            response = self.client.post("/llm", json={"prompt": "help"})
        self.assertEqual(response.status_code, 502)
        detail = response.json()["detail"]
        self.assertNotIn(leaked, detail)
        self.assertIn("Assistant is unavailable:", detail)
        self.assertIn("[redacted]", detail)
