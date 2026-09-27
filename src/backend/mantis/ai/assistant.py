"""The strategy assistant behind ``POST /llm``.

One request runs the :class:`~mantis.ai.agent.AgentHarness` with the model the
user picked (or the environment default), the block tools, and the compiler as
its checker. The response carries the reply, the edited canvas (``null`` when the
agent changed nothing), and the tool steps it took.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.backend.mantis.ai.agent import BLOCK_TOOLS, AgentHarness, Complete, ToolRegistry
from src.backend.mantis.ai.client import ChatClient
from src.backend.mantis.ai.models import resolve_choice
from src.backend.mantis.ai.prompts import load_prompt
from src.backend.mantis.ai.providers import AIConfigError, AIProviderError, Message
from src.backend.mantis.blocks.canvas import CanvasError, empty_canvas, normalize_graph
from src.backend.mantis.blocks.catalog import catalog_for_prompt
from src.backend.mantis.errors import InvalidInput, ServiceUnavailable, UpstreamFailed
from src.backend.mantis.services.compiler import check_document

MAX_PROMPT_LENGTH = 2000
MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_CHARS = 4000


def system_prompt(tools: ToolRegistry = BLOCK_TOOLS) -> str:
    protocol = load_prompt("agent_protocol.md").replace("{tools}", tools.describe()).replace("{catalog}", catalog_for_prompt())
    return f"{load_prompt('assistant_system.md')}\n\n{protocol}"


def ask(
    prompt: str,
    graph: dict | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    history: Sequence[dict[str, str]] = (),
    complete: Complete | None = None,
) -> dict[str, Any]:
    text = prompt.strip()
    if not text:
        raise InvalidInput("Prompt is required")
    if len(text) > MAX_PROMPT_LENGTH:
        raise InvalidInput(f"Prompt is too long (at most {MAX_PROMPT_LENGTH} characters)")
    try:
        canvas = empty_canvas() if graph is None else normalize_graph(graph)
    except CanvasError as exc:
        raise InvalidInput(f"Canvas graph is not valid: {exc}") from exc
    try:
        chosen_provider, chosen_model = resolve_choice(provider, model)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    past = _history(history)

    try:
        if complete is not None:
            result = _harness(complete).run(text, canvas, past)
            used_model = chosen_model
        else:
            with ChatClient.from_env(chosen_provider, chosen_model) as client:
                result = _harness(_completer(client)).run(text, canvas, past)
                used_model = client.model
    except AIConfigError as exc:
        raise ServiceUnavailable(str(exc)) from exc
    except AIProviderError as exc:
        raise UpstreamFailed("Assistant is unavailable") from exc
    return {
        "reply": result.reply,
        "graph": result.graph,
        "steps": [step.to_api() for step in result.steps],
        "model": used_model,
    }


def _harness(complete: Complete) -> AgentHarness:
    return AgentHarness(complete, system_prompt(), checker=check_document)


def _completer(client: ChatClient) -> Complete:
    def complete(system: str, messages: list[Message]) -> str:
        return client.chat(messages, system=system, max_tokens=4096).text

    return complete


def _history(history: Sequence[dict[str, str]]) -> list[Message]:
    """The last few chat turns, oldest first, starting with a user turn and within a size budget."""
    turns = [Message(h["role"], h["content"].strip()) for h in history if h.get("content", "").strip()]  # type: ignore[arg-type]
    kept: list[Message] = []
    budget = MAX_HISTORY_CHARS
    for message in reversed(turns[-MAX_HISTORY_MESSAGES:]):
        budget -= len(message.content)
        if budget < 0:
            break
        kept.insert(0, message)
    while kept and kept[0].role != "user":
        kept.pop(0)
    # The harness appends a user turn, so history must end on an assistant turn.
    while kept and kept[-1].role != "assistant":
        kept.pop()
    return kept
