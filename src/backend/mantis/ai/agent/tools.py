"""Tools the strategy agent can call, and the registry that describes them to the model.

A tool is a name, a one-line description, documented arguments, and a function
``run(context, args) -> result``. The result must be JSON-serializable; it is sent
back to the model verbatim. Raise :class:`ToolError` for a call the model should
fix and retry.

Adding a capability is one registration::

    @registry.tool("describe_block", "Explain one block type.", type="block type id")
    def describe_block(ctx: ToolContext, args: dict) -> dict:
        ...

Nothing else changes: the harness lists every registered tool in the prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.backend.mantis.ai.agent.workspace import ToolError, Workspace
from src.backend.mantis.blocks.catalog import BLOCKS
from src.backend.mantis.blocks.document import document_from_canvas

Checker = Callable[[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class ToolContext:
    workspace: Workspace
    checker: Checker | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    run: Callable[[ToolContext, dict[str, Any]], Any]
    args: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        args = ", ".join(f"{name}: {text}" for name, text in self.args.items()) or "no arguments"
        return f"- {self.name}({args}): {self.description}"


class ToolRegistry:
    def __init__(self, tools: tuple[Tool, ...] = ()):
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, **args: str) -> Callable[[Callable], Callable]:
        """Decorator form of :meth:`register`."""

        def wrap(run: Callable[[ToolContext, dict[str, Any]], Any]) -> Callable:
            self.register(Tool(name, description, run, args))
            return run

        return wrap

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"unknown tool {name!r}; available tools are {', '.join(self._tools)}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self) -> str:
        return "\n".join(t.describe() for t in self._tools.values())

    def extended(self, *tools: Tool) -> "ToolRegistry":
        """A copy of this registry with more tools, leaving this one unchanged."""
        copy = ToolRegistry(tuple(self._tools.values()))
        for t in tools:
            copy.register(t)
        return copy


def _require(args: dict[str, Any], *names: str) -> list[Any]:
    missing = [n for n in names if args.get(n) in (None, "")]
    if missing:
        raise ToolError(f"missing argument {missing[0]!r}")
    return [args[n] for n in names]


def _list_blocks(_: ToolContext, args: dict[str, Any]) -> Any:
    wanted = args.get("type")
    if wanted:
        if wanted not in BLOCKS:
            raise ToolError(f"unknown block type {wanted!r}")
        return BLOCKS[wanted].describe(wanted)
    return [spec.describe(name) for name, spec in BLOCKS.items()]


def _view_canvas(ctx: ToolContext, _: dict[str, Any]) -> Any:
    return ctx.workspace.graph


def _add_block(ctx: ToolContext, args: dict[str, Any]) -> Any:
    (block_type,) = _require(args, "type")
    return ctx.workspace.add_block(str(block_type), args.get("id"), args.get("params"))


def _update_block(ctx: ToolContext, args: dict[str, Any]) -> Any:
    node_id, params = _require(args, "id", "params")
    return ctx.workspace.update_block(str(node_id), params)


def _remove_block(ctx: ToolContext, args: dict[str, Any]) -> Any:
    (node_id,) = _require(args, "id")
    ctx.workspace.remove_block(str(node_id))
    return {"removed": node_id}


def _connect(ctx: ToolContext, args: dict[str, Any]) -> Any:
    source, source_port, target, target_port = _require(args, "source", "source_port", "target", "target_port")
    return ctx.workspace.connect(str(source), str(source_port), str(target), str(target_port))


def _disconnect(ctx: ToolContext, args: dict[str, Any]) -> Any:
    source, target = _require(args, "source", "target")
    return {"removed": ctx.workspace.disconnect(str(source), str(target))}


def _replace_canvas(ctx: ToolContext, args: dict[str, Any]) -> Any:
    (graph,) = _require(args, "graph")
    ctx.workspace.replace(graph)
    return {"nodes": len(ctx.workspace.graph["nodes"]), "edges": len(ctx.workspace.graph["edges"])}


def _check_strategy(ctx: ToolContext, _: dict[str, Any]) -> Any:
    if ctx.checker is None:
        raise ToolError("checking is not available")
    diagnostics = ctx.checker(document_from_canvas(ctx.workspace.graph))
    errors = [d for d in diagnostics if d.get("level") == "error"]
    return {"compiles": not errors, "diagnostics": diagnostics}


BLOCK_TOOLS = ToolRegistry(
    (
        Tool("list_blocks", "Describe every block type, or one block when type is given.", _list_blocks, {"type": "optional block type id"}),
        Tool("view_canvas", "Return the current canvas graph.", _view_canvas),
        Tool(
            "add_block",
            "Add a block and return it with defaults filled in. Omit id to get a fresh one.",
            _add_block,
            {"type": "block type id", "id": "optional new id", "params": "optional object of params"},
        ),
        Tool("update_block", "Change some params of a block; other params keep their values.", _update_block, {"id": "block id", "params": "object of params to change"}),
        Tool("remove_block", "Remove a block and every connection that touched it.", _remove_block, {"id": "block id"}),
        Tool(
            "connect",
            "Wire an output port to an input port. Replaces the wire already on that exec output or data input.",
            _connect,
            {"source": "block id", "source_port": "e.g. exec:then or data:out", "target": "block id", "target_port": "e.g. exec:in or data:a"},
        ),
        Tool("disconnect", "Remove every connection from source to target.", _disconnect, {"source": "block id", "target": "block id"}),
        Tool("replace_canvas", "Replace the whole canvas with a graph of nodes and edges.", _replace_canvas, {"graph": "{nodes: [{id, type, params}], edges: [{source, sourceHandle, target, targetHandle}]}"}),
        Tool("check_strategy", "Compile the current canvas and return compiler diagnostics.", _check_strategy),
    )
)
