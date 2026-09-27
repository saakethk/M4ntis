"""Model-agnostic chat client.

    client = ChatClient("gemini", "gemini-3.8-flash")      # key from GEMINI_API_KEY
    reply = client.chat("How do I build an SMA crossover?", system="You are ...")
    reply = client.chat([Message("user", "..."), Message("assistant", "..."), Message("user", "...")])

    client = ChatClient.from_env()                           # AI_PROVIDER / AI_MODEL from .env

Rate limits, timeouts, and 5xx responses are retried with backoff. Configuration
problems raise :class:`AIConfigError`; provider failures raise :class:`AIProviderError`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from src.backend.mantis.ai.models import default_model
from src.backend.mantis.ai.providers import (
    PROVIDERS,
    AIConfigError,
    AIProviderError,
    ChatRequest,
    ChatResponse,
    HttpCall,
    Message,
)
from src.backend.mantis.config import env, load_env

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
NOT_CONFIGURED = (
    "Assistant is not configured. In the .env file at the repo root, set AI_PROVIDER "
    "(gemini, meta, openai, anthropic, or openai_compatible), AI_MODEL, and that provider's API key."
)


class ChatClient:
    def __init__(
        self,
        provider: str,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        max_retries: int = 2,
        http: httpx.Client | None = None,
    ):
        load_env()
        if provider not in PROVIDERS:
            raise AIConfigError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
        if not model:
            raise AIConfigError("Assistant is not configured. Set AI_MODEL in the .env file at the repo root.")
        self.provider = PROVIDERS[provider]
        self.model = model
        self.api_key = api_key if api_key is not None else (os.environ.get(self.provider.api_key_env) or "").strip()
        # <PROVIDER>_BASE_URL (e.g. META_BASE_URL) points one provider at a gateway or proxy.
        self.base_url = base_url or env(f"{provider.upper()}_BASE_URL") or self.provider.default_base_url
        if not self.base_url:
            raise AIConfigError(f"{provider} needs AI_BASE_URL")
        # A self-hosted OpenAI-compatible server (e.g. Ollama) may not need a key.
        if not self.api_key and provider != "openai_compatible":
            raise AIConfigError(
                f"Assistant is not configured. Set {self.provider.api_key_env} in the .env file at the repo root."
            )
        self.max_retries = max_retries
        self._http = http or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None, **kwargs: Any) -> "ChatClient":
        """Build from explicit choices, falling back to AI_PROVIDER, AI_MODEL, and AI_BASE_URL.

        With no AI_PROVIDER, the provider whose API key is set is used (exactly one
        must be set). With no AI_MODEL, the provider's first listed model is used.
        """
        explicit = (provider or "").strip()
        chosen_provider = explicit or env("AI_PROVIDER") or _provider_from_keys()
        if not chosen_provider:
            raise AIConfigError(NOT_CONFIGURED)
        # AI_MODEL belongs to the environment's provider, not to one picked per request.
        env_model = env("AI_MODEL") if not explicit or explicit == env("AI_PROVIDER") else ""
        chosen_model = (model or env_model or default_model(chosen_provider)).strip()
        kwargs.setdefault("base_url", env("AI_BASE_URL") or None)
        return cls(chosen_provider, chosen_model, **kwargs)

    def chat(
        self,
        messages: str | Iterable[Message | Mapping[str, str]],
        *,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """Send a conversation (oldest first, ending with a user turn) and return the reply."""
        req = ChatRequest(
            model=self.model,
            system=system,
            messages=_normalize(messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        data = self._post(self.provider.build(req, self.api_key, self.base_url))
        try:
            return self.provider.parse(data, req)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AIProviderError(self.provider.name, f"unexpected response shape: {exc!r}") from exc

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ChatClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, call: HttpCall) -> dict[str, Any]:
        name = self.provider.name
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                resp = self._http.post(call.url, headers=call.headers, json=call.json)
            except httpx.HTTPError as exc:
                if last:
                    raise AIProviderError(name, f"request failed: {exc}") from exc
                time.sleep(2**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and not last:
                time.sleep(_retry_after(resp) or 2**attempt)
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


def _provider_from_keys() -> str:
    """The provider whose API key is set, when AI_PROVIDER is blank and exactly one key is."""
    found = [n for n, p in PROVIDERS.items() if n != "openai_compatible" and env(p.api_key_env)]
    if len(found) > 1:
        raise AIConfigError(
            "Assistant is not configured. More than one API key is set. Set AI_PROVIDER to one of: "
            + ", ".join(found)
            + "."
        )
    if found:
        return found[0]
    return "openai_compatible" if env("AI_BASE_URL") else ""


def _normalize(messages: str | Iterable[Message | Mapping[str, str]]) -> tuple[Message, ...]:
    if isinstance(messages, str):
        items = [Message("user", messages)]
    else:
        items = [m if isinstance(m, Message) else Message(m["role"], m["content"]) for m in messages]  # type: ignore[arg-type]
    if not items:
        raise ValueError("at least one message is required")
    for m in items:
        if m.role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {m.role!r}")
    if items[-1].role != "user":
        raise ValueError("the conversation must end with a user message")
    return tuple(items)


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return min(float(resp.headers.get("retry-after", "")), 30.0)
    except ValueError:
        return None
