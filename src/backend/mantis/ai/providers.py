"""Adapters that turn one shared chat request into each vendor's HTTP call.

Every adapter receives the same :class:`ChatRequest` and returns the same
:class:`ChatResponse`, so nothing above this module knows which model answers.
To support another vendor, subclass :class:`Provider` and add it to ``PROVIDERS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


class AIConfigError(RuntimeError):
    """The client can't be built: unknown provider, missing model, or missing API key."""


class AIProviderError(RuntimeError):
    """The provider rejected the request or returned something unreadable."""

    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}" + (f" (HTTP {status})" if status else ""))
        self.provider = provider
        self.status = status


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system: str
    messages: tuple[Message, ...]
    temperature: float | None
    max_tokens: int


@dataclass(frozen=True)
class ChatResponse:
    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HttpCall:
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


class Provider:
    name: str = ""
    label: str = ""
    api_key_env: str = ""
    default_base_url: str = ""
    # Reasoning models (Gemini 3, Muse Spark) are tuned for their default sampling and
    # reject or ignore temperature, so those adapters never send it.
    sends_temperature: bool = True

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        raise NotImplementedError

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    def error_message(self, data: Any) -> str:
        if isinstance(data, dict):
            err = data.get("error", data)
            return str(err.get("message") or err) if isinstance(err, dict) else str(err)
        return str(data)

    def _temperature(self, req: ChatRequest) -> dict[str, float]:
        if not self.sends_temperature or req.temperature is None:
            return {}
        return {"temperature": req.temperature}


class OpenAICompatible(Provider):
    """OpenAI Chat Completions and every API that copies it (Meta, Ollama, vLLM, ...)."""

    name = "openai_compatible"
    label = "OpenAI-compatible server"
    api_key_env = "AI_API_KEY"
    max_tokens_field = "max_tokens"

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        messages = [{"role": "system", "content": req.system}] if req.system else []
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return HttpCall(
            url=f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": req.model,
                "messages": messages,
                self.max_tokens_field: req.max_tokens,
                **self._temperature(req),
            },
        )

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        choice = data["choices"][0]
        content = choice["message"].get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        usage = data.get("usage") or {}
        return ChatResponse(
            text=content or "",
            provider=self.name,
            model=data.get("model") or req.model,
            finish_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )


class OpenAIProvider(OpenAICompatible):
    name = "openai"
    label = "OpenAI"
    api_key_env = "OPENAI_API_KEY"
    default_base_url = "https://api.openai.com/v1"
    max_tokens_field = "max_completion_tokens"


class MetaProvider(OpenAICompatible):
    """Meta Model API (Muse Spark) through its OpenAI-compatible Chat Completions endpoint."""

    name = "meta"
    label = "Meta"
    api_key_env = "META_API_KEY"
    default_base_url = "https://api.meta.ai/v1"
    max_tokens_field = "max_completion_tokens"
    sends_temperature = False


class AnthropicProvider(Provider):
    name = "anthropic"
    label = "Anthropic"
    api_key_env = "ANTHROPIC_API_KEY"
    default_base_url = "https://api.anthropic.com/v1"
    api_version = "2023-06-01"

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        body: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            **self._temperature(req),
        }
        if req.system:
            body["system"] = req.system
        return HttpCall(
            url=f"{base_url.rstrip('/')}/messages",
            headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": self.api_version},
            json=body,
        )

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return ChatResponse(
            text=text,
            provider=self.name,
            model=data.get("model") or req.model,
            finish_reason=data.get("stop_reason"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=data,
        )


class GeminiProvider(Provider):
    name = "gemini"
    label = "Google Gemini"
    api_key_env = "GEMINI_API_KEY"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    sends_temperature = False

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        body: dict[str, Any] = {
            # Gemini calls the assistant role "model".
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in req.messages
            ],
            "generationConfig": {"maxOutputTokens": req.max_tokens, **self._temperature(req)},
        }
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        return HttpCall(
            url=f"{base_url.rstrip('/')}/models/{req.model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=body,
        )

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise AIProviderError(self.name, f"empty response: {reason}")
        first = candidates[0]
        parts = (first.get("content") or {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        return ChatResponse(
            # Thinking models may return thought parts; only answer text is shown.
            text="".join(p.get("text", "") for p in parts if not p.get("thought")),
            provider=self.name,
            model=data.get("modelVersion") or req.model,
            finish_reason=first.get("finishReason"),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            raw=data,
        )


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (GeminiProvider(), MetaProvider(), OpenAIProvider(), AnthropicProvider(), OpenAICompatible())
}
