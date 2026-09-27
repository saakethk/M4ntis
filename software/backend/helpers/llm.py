"""Strategy assistant backed by the configured model provider.

POST /llm sends the user's prompt and the current canvas to AIAgent. The reply
is the model's explanation. When the user asks to build or change a strategy,
the model also returns a graph of blocks the editor can apply.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from helpers.ai_agent import PROVIDERS, AIAgent, AIConfigError, AIProviderError, load_system_prompt
from helpers.canvas import CanvasError, catalog_for_prompt, empty_canvas, normalize_graph

MAX_PROMPT_LENGTH = 2000
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

# Models the assistant panel can select. The first id for a provider is its default.
# Gemini ids are Gemini API model codes. gemini-2.0-flash was shut down on
# 2026-06-01, so the default is gemini-2.5-flash. Meta ids are Llama API model
# ids for https://api.llama.com/compat/v1, the same form as Llama-3.3-70B-Instruct.
ASSISTANT_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
    "meta": ("Llama-3.3-70B-Instruct", "Llama-3.3-8B-Instruct"),
}

APPENDIX = """
## Canvas graph

The user's message includes the current canvas. You can change it. When they ask you to build or edit a strategy, end your reply with one fenced JSON block and nothing after it. The prose before the fence is what they read. Explain the rule, then the graph is what gets placed if they accept it.

Return the whole canvas, not a list of changes. Keep the id of every block you leave in place. Add a block by choosing a new short id. Remove a block by leaving it out, along with every edge that touched it. Always include the Start block with id "start".

```json
{"graph":{"nodes":[{"id":"start","type":"start","params":{"resolution":"5m","startingBalance":100000}},{"id":"t0","type":"get_ticker","params":{"symbol":"AAPL"}},{"id":"fast","type":"sma","params":{"n":10,"buffer":0}},{"id":"slow","type":"sma","params":{"n":30,"buffer":0}},{"id":"cross","type":"if","params":{"operator":">"}},{"id":"buy","type":"buy","params":{"quantity":10,"buffer":0}},{"id":"sell","type":"sell","params":{"quantity":10,"buffer":0}}],"edges":[{"source":"start","sourceHandle":"exec:out","target":"cross","targetHandle":"exec:in"},{"source":"fast","sourceHandle":"data:out","target":"cross","targetHandle":"data:a"},{"source":"slow","sourceHandle":"data:out","target":"cross","targetHandle":"data:b"},{"source":"cross","sourceHandle":"exec:then","target":"buy","targetHandle":"exec:in"},{"source":"cross","sourceHandle":"exec:else","target":"sell","targetHandle":"exec:in"}]}}
```

Port ids are `exec:out`, `exec:then`, `exec:else`, `exec:body`, `exec:after`, `exec:in`, `data:out`, `data:a`, `data:b`, `data:upper`, `data:middle`, `data:lower`, `data:index`, `data:value`, and `data:base` or `data:x` where that block has them. An exec output and a data input each take one edge. Exec connects only to exec, data only to data. Do not make a cycle.

Get ticker blocks fill BUF0, BUF1, BUF2, BUF3, BUF4 in alphabetical id order, so name them t0, t1, t2 when the order matters. Indicators, Buy, and Sell do not take a wire from Get ticker; set their `buffer` to that slot. To compare the price itself, wire Get ticker `data:out` into an If input. There are at most five Get ticker blocks.

For a question that does not change the strategy, do not include a graph block.

Blocks you may use:
""".strip()


def system_prompt() -> str:
    return f"{load_system_prompt()}\n\n{APPENDIX}\n{catalog_for_prompt()}"


def resolve_assistant_model(provider: str | None, model: str | None) -> tuple[str | None, str | None]:
    """Return provider and model overrides for AIAgent.from_env.

    (None, None) keeps today's environment default. Unknown names raise ValueError.
    """
    provider_text = (provider or "").strip()
    model_text = (model or "").strip()
    if not provider_text and not model_text:
        return None, None
    if provider_text and provider_text not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_text}")
    if model_text:
        owner = _model_provider(model_text)
        if owner is None or (provider_text and provider_text != owner):
            raise ValueError(f"Unknown model: {model_text}")
        return owner, model_text
    listed = ASSISTANT_MODELS.get(provider_text)
    if not listed:
        raise ValueError("Unknown model")
    return provider_text, listed[0]


def ask(
    prompt: str,
    graph: dict | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    complete: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Send one prompt and the current canvas. Return reply text plus an optional graph."""
    text = prompt.strip()
    if not text:
        raise ValueError("Prompt is required")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt is too long")
    try:
        canvas = empty_canvas() if graph is None else normalize_graph(graph)
    except CanvasError as exc:
        raise ValueError("Canvas graph is not valid") from exc
    selected_provider, selected_model = resolve_assistant_model(provider, model)
    if complete is None:
        raw = _complete(_message(text, canvas), selected_provider, selected_model)
    else:
        raw = complete(_message(text, canvas))
    reply, proposed = _split(raw)
    applied: dict | None = None
    if proposed is not None:
        try:
            applied = normalize_graph(proposed)
        except CanvasError:
            applied = None
    return {"reply": reply, "dummy": False, "graph": applied}


def _message(prompt: str, graph: dict) -> str:
    canvas = json.dumps(graph, separators=(",", ":"))
    return f"Current canvas:\n{canvas}\n\nUser request:\n{prompt}"


def _model_provider(model: str) -> str | None:
    for name, models in ASSISTANT_MODELS.items():
        if model in models:
            return name
    return None


def _complete(prompt: str, provider: str | None = None, model: str | None = None) -> str:
    kwargs: dict[str, str] = {}
    if provider:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model
    with AIAgent.from_env(**kwargs) as agent:
        response = agent.chat(prompt, system_prompt=system_prompt(), temperature=0.2, max_tokens=4096)
    if not response.text.strip():
        raise AIProviderError(response.provider, "empty response")
    return response.text


def _split(text: str) -> tuple[str, dict | None]:
    stripped = text.strip()
    if not stripped:
        raise AIProviderError("assistant", "empty response")
    whole = _json_object(stripped)
    if whole is not None and isinstance(whole.get("reply"), str) and whole["reply"].strip():
        return whole["reply"].strip(), _graph_value(whole.get("graph"))
    graph: dict | None = None
    reply = stripped
    for match in _FENCE.finditer(stripped):
        payload = _json_object(match.group(1))
        if payload is None or "graph" not in payload:
            continue
        graph = _graph_value(payload.get("graph"))
        reply = f"{stripped[: match.start()]}{stripped[match.end() :]}".strip()
    if graph is not None and not reply:
        reply = "Updated the blocks on the canvas."
    return reply, graph


def _graph_value(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


def _json_object(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


__all__ = [
    "AIConfigError",
    "AIProviderError",
    "ASSISTANT_MODELS",
    "MAX_PROMPT_LENGTH",
    "ask",
    "resolve_assistant_model",
    "system_prompt",
]
