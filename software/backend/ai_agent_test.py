"""Tests for the model-agnostic AI agent. No network: every provider is faked with httpx.MockTransport."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from helpers.ai_agent import (
    PROVIDERS,
    AIAgent,
    AIConfigError,
    AIProviderError,
    Message,
    load_system_prompt,
)

REPLIES = {
    "openai": {
        "model": "m", "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 2},
    },
    "meta": {
        "model": "m", "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 2},
    },
    "openai_compatible": {
        "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    },
    "anthropic": {
        "model": "m", "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 2},
    },
    "gemini": {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "hi"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 2},
    },
}

HISTORY = [
    Message("user", "What is a tick?"),
    Message("assistant", "One bar at your chosen resolution."),
    {"role": "user", "content": "Build me an SMA crossover."},
]


def make_agent(provider: str, handler, **kwargs) -> AIAgent:
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("base_url", "http://llm.test/v1" if provider == "openai_compatible" else None)
    return AIAgent(provider, "m", client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


class ProviderRequestTest(unittest.TestCase):
    def capture(self, provider: str, **kwargs):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=REPLIES[provider])

        reply = make_agent(provider, handler, system_prompt="SYS", **kwargs).chat(HISTORY)
        return seen["request"], seen["body"], reply

    def test_every_provider_returns_the_same_shape(self):
        for provider in PROVIDERS:
            with self.subTest(provider):
                _, _, reply = self.capture(provider)
                self.assertEqual(reply.text, "hi")
                self.assertEqual(reply.provider, provider)
                self.assertIsNotNone(reply.finish_reason)

    def test_openai_request(self):
        req, body, reply = self.capture("openai")
        self.assertEqual(str(req.url), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(req.headers["authorization"], "Bearer test-key")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
        self.assertIn("max_completion_tokens", body)
        self.assertEqual((reply.input_tokens, reply.output_tokens), (11, 2))

    def test_meta_uses_muse_chat_completions(self):
        req, body, _ = self.capture("meta")
        self.assertEqual(str(req.url), "https://api.meta.ai/v1/chat/completions")
        self.assertEqual(req.headers["authorization"], "Bearer test-key")
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)

    def test_meta_request_body_uses_muse_spark_model_id(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=REPLIES["meta"])

        AIAgent(
            "meta",
            "muse-spark-1.3",
            api_key="test-key",
            system_prompt="SYS",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ).chat("ping")
        self.assertEqual(seen["body"]["model"], "muse-spark-1.3")
        self.assertNotIn("max_tokens", seen["body"])
        self.assertEqual(seen["body"]["max_completion_tokens"], 1024)
        self.assertEqual(seen["body"]["temperature"], 0.3)

    def test_anthropic_request(self):
        req, body, reply = self.capture("anthropic")
        self.assertEqual(str(req.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers["x-api-key"], "test-key")
        self.assertIn("anthropic-version", req.headers)
        self.assertEqual(body["system"], "SYS")
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        self.assertEqual(reply.finish_reason, "end_turn")

    def test_gemini_request(self):
        req, body, reply = self.capture("gemini")
        self.assertEqual(
            str(req.url), "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent"
        )
        self.assertEqual(req.headers["x-goog-api-key"], "test-key")
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "SYS"}]})
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 1024)
        self.assertEqual(reply.output_tokens, 2)

    def test_self_hosted_server_needs_no_key(self):
        req, _, _ = self.capture("openai_compatible", api_key="")
        self.assertEqual(str(req.url), "http://llm.test/v1/chat/completions")
        self.assertNotIn("authorization", req.headers)


class AgentBehaviourTest(unittest.TestCase):
    def test_same_system_prompt_for_every_provider(self):
        prompts = set()

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            prompts.add(
                body.get("system")
                or (body.get("systemInstruction") or {}).get("parts", [{}])[0].get("text")
                or body["messages"][0]["content"]
            )
            return httpx.Response(200, json=REPLIES[provider])

        for provider in PROVIDERS:
            make_agent(provider, handler).chat("hello")
        self.assertEqual(prompts, {load_system_prompt()})
        self.assertIn("Mantis", load_system_prompt())

    def test_string_input_and_overrides(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
            self.assertEqual(body["temperature"], 0.9)
            self.assertEqual(body["max_tokens"], 50)
            return httpx.Response(200, json=REPLIES["anthropic"])

        make_agent("anthropic", handler).chat("hello", temperature=0.9, max_tokens=50)

    def test_bad_conversations_are_rejected(self):
        agent = make_agent("openai", lambda r: httpx.Response(200, json=REPLIES["openai"]))
        with self.assertRaises(ValueError):
            agent.chat([])
        with self.assertRaises(ValueError):
            agent.chat([Message("assistant", "hi")])
        with self.assertRaises(ValueError):
            agent.chat([{"role": "system", "content": "x"}, {"role": "user", "content": "y"}])

    def test_config_errors(self):
        with self.assertRaises(AIConfigError):
            AIAgent("nope", "m", api_key="k")
        with self.assertRaises(AIConfigError):
            AIAgent("openai", "", api_key="k")
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(AIConfigError):
                AIAgent("openai", "m")
        with patch("helpers.ai_agent._load_repo_env"), patch.dict("os.environ", {"OPENAI_API_KEY": "   "}):
            with self.assertRaises(AIConfigError):
                AIAgent("openai", "m")

    def test_from_env(self):
        env = {"AI_PROVIDER": "gemini", "AI_MODEL": "some-model", "GEMINI_API_KEY": "k"}
        with patch.dict("os.environ", env):
            agent = AIAgent.from_env()
        self.assertEqual((agent.provider.name, agent.model, agent.api_key), ("gemini", "some-model", "k"))
        agent.close()

    def test_from_env_override_uses_that_providers_key(self):
        env = {
            "AI_PROVIDER": "gemini",
            "AI_MODEL": "gemini-2.5-flash",
            "GEMINI_API_KEY": "gemini-key",
            "META_API_KEY": "meta-key",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "AI_API_KEY": "",
            "AI_BASE_URL": "",
        }
        with patch("helpers.ai_agent._load_repo_env"), patch.dict("os.environ", env):
            agent = AIAgent.from_env(provider="meta", model="muse-spark-1.1")
        self.assertEqual(agent.provider.name, "meta")
        self.assertEqual(agent.model, "muse-spark-1.1")
        self.assertEqual(agent.base_url, "https://api.meta.ai/v1")
        self.assertEqual(agent.api_key, "meta-key")
        agent.close()

    def test_from_env_override_names_the_missing_key(self):
        env = {
            "AI_PROVIDER": "gemini",
            "AI_MODEL": "gemini-2.5-flash",
            "GEMINI_API_KEY": "gemini-key",
            "META_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "AI_API_KEY": "",
        }
        with patch("helpers.ai_agent._load_repo_env"), patch.dict("os.environ", env):
            with self.assertRaises(AIConfigError) as caught:
                AIAgent.from_env(provider="meta", model="muse-spark-1.3")
        self.assertIn("META_API_KEY", str(caught.exception))
        self.assertIn(".env", str(caught.exception))

    def test_from_env_uses_the_only_api_key(self):
        env = {
            "AI_PROVIDER": "",
            "AI_MODEL": "",
            "AI_BASE_URL": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "META_API_KEY": "",
            "AI_API_KEY": "",
            "GEMINI_API_KEY": "k",
        }
        # Ignore the repo-root .env so a local AI_MODEL does not hide the code default.
        with patch("helpers.ai_agent._load_repo_env"), patch.dict("os.environ", env):
            agent = AIAgent.from_env()
        self.assertEqual(agent.provider.name, "gemini")
        self.assertEqual(agent.model, "gemini-2.5-flash")
        agent.close()

    def test_from_env_names_the_missing_settings(self):
        env = {
            "AI_PROVIDER": "",
            "AI_MODEL": "",
            "AI_BASE_URL": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GEMINI_API_KEY": "",
            "META_API_KEY": "",
            "AI_API_KEY": "",
        }
        # Ignore the repo-root .env so a local AI_PROVIDER does not hide the empty-config error.
        with patch("helpers.ai_agent._load_repo_env"), patch.dict("os.environ", env):
            with self.assertRaises(AIConfigError) as caught:
                AIAgent.from_env()
        self.assertIn("AI_PROVIDER", str(caught.exception))
        self.assertIn(".env", str(caught.exception))

    def test_provider_error_carries_status_and_message(self):
        agent = make_agent(
            "openai", lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}), max_retries=0
        )
        with self.assertRaises(AIProviderError) as ctx:
            agent.chat("hi")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("bad key", str(ctx.exception))

    def test_retries_rate_limits_then_succeeds(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"})
            return httpx.Response(200, json=REPLIES["gemini"])

        reply = make_agent("gemini", handler).chat("hi")
        self.assertEqual((reply.text, len(calls)), ("hi", 3))

    def test_unexpected_shape_is_a_provider_error(self):
        agent = make_agent("openai", lambda r: httpx.Response(200, json={"choices": []}))
        with self.assertRaises(AIProviderError):
            agent.chat("hi")

    def test_blocked_gemini_prompt(self):
        agent = make_agent("gemini", lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
        with self.assertRaises(AIProviderError) as ctx:
            agent.chat("hi")
        self.assertIn("SAFETY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
