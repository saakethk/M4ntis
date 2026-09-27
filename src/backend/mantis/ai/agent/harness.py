"""A tool-using loop that lets any chat model build and edit block strategies.

Each turn the model answers with one JSON object:

    {"tool_calls": [{"name": "add_block", "args": {"type": "sma", "params": {"n": 10}}}]}
    {"reply": "Text the user reads."}

Tool calls run against a :class:`Workspace` and their results go back to the model
as the next user message. The loop ends on a ``reply``, on plain text (treated as
the reply), or when the step budget runs out.

The protocol is plain JSON in the message text rather than a vendor's native
function calling, so every provider behind :class:`mantis.ai.client.ChatClient`
works unchanged, and a new tool is one entry in a :class:`ToolRegistry`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.backend.mantis.ai.agent.tools import BLOCK_TOOLS, Checker, ToolContext, ToolRegistry
from src.backend.mantis.ai.agent.workspace import ToolError, Workspace
from src.backend.mantis.ai.providers import AIProviderError, Message

Complete = Callable[[str, list[Message]], str]
"""``complete(system_prompt, messages) -> model text``."""

MAX_STEPS = 8
MAX_CALLS_PER_STEP = 16
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Step:
    """One executed tool call, reported to the UI so users can see what the agent did."""

    tool: str
    args: dict[str, Any]
    ok: bool
    detail: str

    def to_api(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "ok": self.ok, "detail": self.detail}


@dataclass
class AgentResult:
    reply: str
    graph: dict[str, list] | None
    steps: list[Step] = field(default_factory=list)


class AgentHarness:
    def __init__(
        self,
        complete: Complete,
        system_prompt: str,
        *,
        tools: ToolRegistry = BLOCK_TOOLS,
        checker: Checker | None = None,
        max_steps: int = MAX_STEPS,
    ):
        self.complete = complete
        self.system_prompt = system_prompt
        self.tools = tools
        self.checker = checker
        self.max_steps = max_steps

    def run(self, request: str, canvas: dict[str, list], history: Sequence[Message] = ()) -> AgentResult:
        workspace = Workspace(canvas)
        context = ToolContext(workspace, self.checker)
        steps: list[Step] = []
        messages = [*history, Message("user", _opening(request, workspace.graph))]

        for _ in range(self.max_steps):
            text = self.complete(self.system_prompt, messages).strip()
            if not text:
                raise AIProviderError("assistant", "empty response")
            action = _parse_action(text)
            calls = action.get("tool_calls") if action else None
            if not calls:
                reply = action.get("reply") if action else None
                if not isinstance(reply, str) or not reply.strip():
                    reply = _legacy_reply(text, workspace)
                return self._finish(reply.strip(), workspace, steps)
            results = [self._call(call, context, steps) for call in calls[:MAX_CALLS_PER_STEP]]
            messages += [
                Message("assistant", text),
                Message("user", "Tool results:\n" + json.dumps(results, separators=(",", ":"), default=str)),
            ]

        note = "I stopped after the maximum number of steps."
        return self._finish(note + (" The canvas has my changes so far." if workspace.changed else ""), workspace, steps)

    def _call(self, call: Any, context: ToolContext, steps: list[Step]) -> dict[str, Any]:
        name = str(call.get("name", "")) if isinstance(call, dict) else ""
        args = call.get("args") if isinstance(call, dict) and isinstance(call.get("args"), dict) else {}
        try:
            result = self.tools.get(name).run(context, args)
        except ToolError as exc:
            steps.append(Step(name, args, False, str(exc)))
            return {"name": name, "ok": False, "error": str(exc)}
        steps.append(Step(name, args, True, _summarize(result)))
        return {"name": name, "ok": True, "result": result}

    @staticmethod
    def _finish(reply: str, workspace: Workspace, steps: list[Step]) -> AgentResult:
        return AgentResult(reply, workspace.graph if workspace.changed else None, steps)


def _opening(request: str, graph: dict[str, list]) -> str:
    canvas = json.dumps(graph, separators=(",", ":"))
    return f"Current canvas:\n{canvas}\n\nUser request:\n{request}"


def _parse_action(text: str) -> dict[str, Any] | None:
    """The JSON action in a reply, whether bare or inside a code fence."""
    candidates = [text, *(m.group(1) for m in _FENCE.finditer(text))]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("tool_calls" in parsed or "reply" in parsed):
            return parsed
    return None


def _legacy_reply(text: str, workspace: Workspace) -> str:
    """Plain prose, optionally ending in a fenced ``{"graph": ...}`` block (one-shot answers)."""
    reply = text
    for match in _FENCE.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("graph"), dict):
            try:
                workspace.replace(payload["graph"])
            except ToolError:
                pass
            reply = (text[: match.start()] + text[match.end() :]).strip()
    return reply or "Updated the blocks on the canvas."


def _summarize(result: Any) -> str:
    if isinstance(result, dict) and "id" in result and "type" in result:
        return f"{result['type']} {result['id']}"
    if isinstance(result, dict) and "compiles" in result:
        return "compiles" if result["compiles"] else f"{len(result['diagnostics'])} diagnostics"
    if isinstance(result, dict) and "source" in result and "target" in result:
        return f"{result['source']}.{result['sourceHandle']} -> {result['target']}.{result['targetHandle']}"
    if isinstance(result, list):
        return f"{len(result)} items"
    return "done"
