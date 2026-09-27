"""Models the product offers, and which one a request should use.

``ASSISTANT_MODELS`` is the single list the editor's model picker shows (served by
``GET /llm/models``). The first model listed for a provider is that provider's
default. Retired models (Gemini 2.x, Llama 3.3 on the old Llama API) are not
listed; a request naming one is rejected before any API call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from mantis.ai.providers import PROVIDERS
from mantis.config import env, load_env


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    label: str


ASSISTANT_MODELS: tuple[ModelChoice, ...] = (
    ModelChoice("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash"),
    ModelChoice("gemini", "gemini-3.7-flash", "Gemini 3.7 Flash"),
    ModelChoice("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
    ModelChoice("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)"),
    ModelChoice("meta", "muse-spark-1.3", "Muse Spark 1.3"),
    ModelChoice("meta", "muse-spark-1.2", "Muse Spark 1.2"),
)

# Post summaries always use Meta's Muse Spark. POST_SUMMARY_MODEL may pick another Muse model.
SUMMARY_PROVIDER = "meta"
DEFAULT_SUMMARY_MODEL = "muse-spark-1.3"


def default_model(provider: str) -> str:
    """The first listed model for a provider, or "" (the provider then needs AI_MODEL)."""
    return next((c.model for c in ASSISTANT_MODELS if c.provider == provider), "")


def resolve_choice(provider: str | None, model: str | None) -> tuple[str | None, str | None]:
    """Validate a picker choice. ``(None, None)`` means "use the environment default".

    Raises ValueError for an unknown provider, an unlisted model, or a model sent
    with a provider that does not serve it.
    """
    provider_text, model_text = (provider or "").strip(), (model or "").strip()
    if not provider_text and not model_text:
        return None, None
    if provider_text and provider_text not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_text}")
    if model_text:
        owner = next((c.provider for c in ASSISTANT_MODELS if c.model == model_text), None)
        if owner is None or (provider_text and provider_text != owner):
            raise ValueError(f"Unknown model: {model_text}")
        return owner, model_text
    listed = default_model(provider_text)
    if not listed:
        raise ValueError(f"Unknown model for provider {provider_text}")
    return provider_text, listed


def summary_model() -> str:
    return env("POST_SUMMARY_MODEL", DEFAULT_SUMMARY_MODEL)


def has_key(provider: str) -> bool:
    load_env()
    return bool((os.environ.get(PROVIDERS[provider].api_key_env) or "").strip())


def models_for_api() -> dict[str, object]:
    """The picker list, each entry flagged with whether its API key is configured."""
    return {
        "models": [
            {"provider": c.provider, "model": c.model, "label": c.label, "available": has_key(c.provider)}
            for c in ASSISTANT_MODELS
        ],
        "default": _environment_default(),
    }


def _environment_default() -> dict[str, str] | None:
    provider, model = env("AI_PROVIDER"), env("AI_MODEL")
    if provider in PROVIDERS and any(c.provider == provider and c.model == model for c in ASSISTANT_MODELS):
        return {"provider": provider, "model": model}
    if provider in PROVIDERS and not model and default_model(provider):
        return {"provider": provider, "model": default_model(provider)}
    return None
