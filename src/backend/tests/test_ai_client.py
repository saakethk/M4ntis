"""Provider requests and client configuration. HTTP is mocked; no request leaves the process."""

from __future__ import annotations

import json

import httpx
import pytest

from src.backend.mantis.ai.client import ChatClient
from src.backend.mantis.ai.models import ASSISTANT_MODELS, models_for_api, resolve_choice
from src.backend.mantis.ai.providers import AIConfigError, AIProviderError

REPLIES = {
    "gemini": {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": "hi"}]}, "finishReason": "STOP"}]},
    "meta": {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3}},
}


@pytest.fixture(autouse=True)
def no_ai_env(monkeypatch):
    for name in ("AI_PROVIDER", "AI_MODEL", "AI_BASE_URL", "META_BASE_URL", "GEMINI_API_KEY", "META_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def capture(provider: str, model: str):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=REPLIES[provider])

    client = ChatClient(provider, model, api_key="k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    reply = client.chat("hello", system="be brief", temperature=0.2, max_tokens=50)
    return seen[0], json.loads(seen[0].content), reply


def test_gemini_request_omits_temperature_and_thoughts():
    request, body, reply = capture("gemini", "gemini-3.8-flash")
    assert str(request.url).endswith("/models/gemini-3.8-flash:generateContent")
    assert body["generationConfig"] == {"maxOutputTokens": 50}
    assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert reply.text == "hi"


def test_meta_uses_the_model_api_with_max_completion_tokens():
    request, body, reply = capture("meta", "muse-spark-1.3")
    assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer k"
    assert body["max_completion_tokens"] == 50 and "temperature" not in body
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert reply.input_tokens == 3


def test_provider_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("META_BASE_URL", "http://gateway.local/v1")
    assert ChatClient("meta", "muse-spark-1.3", api_key="k").base_url == "http://gateway.local/v1"


def test_retries_then_raises_provider_error(monkeypatch):
    monkeypatch.setattr("mantis.ai.client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "busy"}})

    client = ChatClient("meta", "muse-spark-1.3", api_key="k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AIProviderError, match="busy"):
        client.chat("hi")
    assert len(calls) == 3


def test_from_env_picks_the_only_configured_key(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "m")
    client = ChatClient.from_env()
    assert (client.provider.name, client.model) == ("meta", "muse-spark-1.3")


def test_missing_key_names_the_setting(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    with pytest.raises(AIConfigError, match="GEMINI_API_KEY"):
        ChatClient.from_env()
    with pytest.raises(AIConfigError, match="META_API_KEY"):
        ChatClient.from_env("meta", "muse-spark-1.2")


def test_retired_models_are_not_offered():
    listed = {c.model for c in ASSISTANT_MODELS}
    assert not any(m.startswith(("gemini-2", "Llama-3")) for m in listed)
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_choice("gemini", "gemini-2.0-flash")


def test_resolve_choice():
    assert resolve_choice(None, None) == (None, None)
    assert resolve_choice(None, "muse-spark-1.2") == ("meta", "muse-spark-1.2")
    assert resolve_choice("gemini", None) == ("gemini", "gemini-3.8-flash")
    with pytest.raises(ValueError, match="Unknown provider"):
        resolve_choice("cursor", None)
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_choice("gemini", "muse-spark-1.3")


def test_models_for_api_flags_configured_keys(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "m")
    listed = models_for_api()["models"]
    assert all(m["available"] == (m["provider"] == "meta") for m in listed)
