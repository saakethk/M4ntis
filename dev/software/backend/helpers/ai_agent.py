"""Model-agnostic chat client for the Mantis assistant.

One `AIAgent` talks to any supported provider with the same system prompt and the same
message format. Each provider is a small adapter that turns the shared request into that
vendor's HTTP call and turns the reply back into a `ChatResponse`, so nothing above this
module needs to know which model is answering.

    agent = AIAgent("gemini", model="<model id>")          # key from GEMINI_API_KEY
    reply = agent.chat("How do I make an SMA crossover?")
    history = [*history, Message("user", question)]
    reply = agent.chat(history)

    agent = AIAgent.from_env()                              # AI_PROVIDER / AI_MODEL from .env
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import httpx
from dotenv import dotenv_values

Role = Literal["user", "assistant"]

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "assistant_system.md"
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class AIConfigError(RuntimeError):
    """The agent can't be built: unknown provider, missing model or missing API key."""


class AIProviderError(RuntimeError):
    """The provider rejected the request or returned something we couldn't read."""

    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}" + (f" (HTTP {status})" if status else ""))
        self.provider = provider
        self.status = status


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


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
class ChatRequest:
    """What every adapter receives, regardless of vendor."""

    model: str
    system: str
    messages: tuple[Message, ...]
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class HttpCall:
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


class Provider:
    """Adapter for one vendor API. Subclass and add to PROVIDERS to support another."""

    name: str = ""
    api_key_env: str = ""
    default_base_url: str = ""

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        raise NotImplementedError

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    def error_message(self, data: Any) -> str:
        if isinstance(data, dict):
            err = data.get("error", data)
            if isinstance(err, dict):
                return str(err.get("message") or err)
            return str(err)
        return str(data)


class OpenAICompatible(Provider):
    """OpenAI Chat Completions, and every API that copies it (Meta Llama API, Ollama, vLLM, ...)."""

    name = "openai_compatible"
    api_key_env = "AI_API_KEY"
    # Newer OpenAI models only accept max_completion_tokens; most compatible servers want max_tokens.
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
                "temperature": req.temperature,
                self.max_tokens_field: req.max_tokens,
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
    api_key_env = "OPENAI_API_KEY"
    default_base_url = "https://api.openai.com/v1"
    max_tokens_field = "max_completion_tokens"


class MetaProvider(OpenAICompatible):
    """Meta's Llama API through its OpenAI-compatible endpoint."""

    name = "meta"
    api_key_env = "META_API_KEY"
    default_base_url = "https://api.llama.com/compat/v1"


class AnthropicProvider(Provider):
    name = "anthropic"
    api_key_env = "ANTHROPIC_API_KEY"
    default_base_url = "https://api.anthropic.com/v1"
    api_version = "2023-06-01"

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        body: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        if req.system:
            body["system"] = req.system
        return HttpCall(
            url=f"{base_url.rstrip('/')}/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": self.api_version,
            },
            json=body,
        )

    def parse(self, data: dict[str, Any], req: ChatRequest) -> ChatResponse:
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
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
    api_key_env = "GEMINI_API_KEY"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def build(self, req: ChatRequest, api_key: str, base_url: str) -> HttpCall:
        body: dict[str, Any] = {
            # Gemini calls the assistant role "model".
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in req.messages
            ],
            "generationConfig": {"temperature": req.temperature, "maxOutputTokens": req.max_tokens},
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
            text="".join(p.get("text", "") for p in parts),
            provider=self.name,
            model=data.get("modelVersion") or req.model,
            finish_reason=first.get("finishReason"),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            raw=data,
        )


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (OpenAIProvider(), AnthropicProvider(), GeminiProvider(), MetaProvider(), OpenAICompatible())
}

# Used when a key is present but AI_MODEL was left blank.
_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
    "meta": "Llama-3.3-70B-Instruct",
}
_NOT_CONFIGURED = (
    "Assistant is not configured. In the .env file at the repo root, set AI_PROVIDER "
    "(openai, anthropic, gemini, meta, or openai_compatible), AI_MODEL, and that provider's API key."
)


def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text().strip()


class AIAgent:
    """Chat with any provider in PROVIDERS using one shared system prompt."""

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        system_prompt: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ):
        _load_repo_env()
        if provider not in PROVIDERS:
            raise AIConfigError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
        if not model:
            raise AIConfigError("a model id is required")
        self.provider = PROVIDERS[provider]
        self.model = model
        self.system_prompt = load_system_prompt() if system_prompt is None else system_prompt
        self.api_key = api_key if api_key is not None else os.environ.get(self.provider.api_key_env, "")
        self.base_url = base_url or self.provider.default_base_url
        if not self.base_url:
            raise AIConfigError(f"{provider} needs a base_url")
        # A self-hosted OpenAI-compatible server (e.g. Ollama) may not need a key.
        if not self.api_key and provider != "openai_compatible":
            raise AIConfigError(
                f"Assistant is not configured. Set {self.provider.api_key_env} in the .env file at the repo root."
            )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self._client = client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, **overrides: Any) -> "AIAgent":
        """Build from AI_PROVIDER, AI_MODEL and (optionally) AI_BASE_URL in the environment or .env."""
        _load_repo_env()
        provider = (overrides.pop("provider", None) or os.environ.get("AI_PROVIDER") or "").strip()
        model = (overrides.pop("model", None) or os.environ.get("AI_MODEL") or "").strip()
        if not provider:
            provider = _provider_from_keys()
        if not provider:
            raise AIConfigError(_NOT_CONFIGURED)
        if not model:
            model = _DEFAULT_MODEL.get(provider, "")
        if not model:
            raise AIConfigError(
                "Assistant is not configured. Set AI_MODEL in the .env file at the repo root."
            )
        overrides.setdefault("base_url", (os.environ.get("AI_BASE_URL") or "").strip() or None)
        return cls(provider, model, **overrides)

    def chat(
        self,
        messages: str | Iterable[Message | Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> ChatResponse:
        """Send a conversation and return the assistant's reply.

        `messages` is either one user message as a string, or the full history as Message objects
        or {"role", "content"} dicts, oldest first, ending with the user's latest turn.
        """
        req = ChatRequest(
            model=self.model,
            system=self.system_prompt if system_prompt is None else system_prompt,
            messages=_normalize(messages),
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
        )
        call = self.provider.build(req, self.api_key, self.base_url)
        data = self._post(call)
        try:
            return self.provider.parse(data, req)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AIProviderError(self.provider.name, f"unexpected response shape: {exc!r}") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AIAgent":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, call: HttpCall) -> dict[str, Any]:
        name = self.provider.name
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.post(call.url, headers=call.headers, json=call.json)
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise AIProviderError(name, f"request failed: {exc}") from exc
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                delay = _retry_after(resp)
                time.sleep(2**attempt if delay is None else delay)
                continue
            try:
                data = resp.json()
            except ValueError:
                data = resp.text
            if resp.is_error:
                raise AIProviderError(name, self.provider.error_message(data), resp.status_code)
            if not isinstance(data, dict):
                raise AIProviderError(name, "response was not a JSON object", resp.status_code)
            return data
        raise AssertionError("unreachable")


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".env.example").is_file() or (candidate / ".git").exists():
            return candidate
    return Path.cwd()


def _load_repo_env() -> None:
    """Fill blank AI settings from the repo-root .env. Values already set are kept."""
    path = _repo_root() / ".env"
    if not path.is_file():
        return
    for key, value in dotenv_values(path).items():
        if value and not os.environ.get(key, "").strip():
            os.environ[key] = value


def _provider_from_keys() -> str:
    """Pick a provider when AI_PROVIDER is blank and exactly one API key is set."""
    found = [
        name
        for name, provider in PROVIDERS.items()
        if name != "openai_compatible" and os.environ.get(provider.api_key_env, "").strip()
    ]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise AIConfigError(
            "Assistant is not configured. More than one API key is set. Set AI_PROVIDER to one of: "
            + ", ".join(found)
            + "."
        )
    if (os.environ.get("AI_BASE_URL") or "").strip():
        return "openai_compatible"
    return ""


def _normalize(messages: str | Iterable[Message | Mapping[str, str]]) -> tuple[Message, ...]:
    if isinstance(messages, str):
        items: list[Message] = [Message("user", messages)]
    else:
        items = [m if isinstance(m, Message) else Message(m["role"], m["content"]) for m in messages]  # type: ignore[arg-type]
    if not items:
        raise ValueError("at least one message is required")
    for m in items:
        if m.role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {m.role!r} (the system prompt is set on the agent)")
    if items[-1].role != "user":
        raise ValueError("the conversation must end with a user message")
    return tuple(items)


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return min(float(resp.headers.get("retry-after", "")), 30.0)
    except ValueError:
        return None
