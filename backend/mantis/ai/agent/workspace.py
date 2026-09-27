"""The canvas an agent edits during one request.

Every mutation is applied to a copy and the whole graph is re-validated with
:func:`mantis.blocks.canvas.normalize_graph`. The change is kept only when the
result is still a graph the editor can place, so the workspace is valid after
every step and a failed tool call leaves it untouched.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable
from typing import Any

from backend.mantis.blocks.canvas import START_ID, CanvasError, normalize_graph
from backend.mantis.blocks.catalog import BLOCKS

Graph = dict[str, list]


class ToolError(ValueError):
    """A tool call could not be carried out. The message is shown to the model."""


class Workspace:
    def __init__(self, graph: Graph):
        self._graph = normalize_graph(graph)
        self.changed = False

    @property
    def graph(self) -> Graph:
        return copy.deepcopy(self._graph)

    def node(self, node_id: str) -> dict[str, Any]:
        found = next((n for n in self._graph["nodes"] if n["id"] == node_id), None)
        if found is None:
            raise ToolError(f"there is no block with id {node_id!r}")
        return found

    def add_block(self, block_type: str, node_id: str | None = None, params: dict | None = None) -> dict[str, Any]:
        if block_type not in BLOCKS:
            raise ToolError(f"unknown block type {block_type!r}; call list_blocks to see the catalog")
        if block_type == "start":
            raise ToolError("the canvas already has its Start block")
        new_id = node_id or self._fresh_id(block_type)
        self._apply(lambda g: g["nodes"].append({"id": new_id, "type": block_type, "params": params or {}}))
        return self.node(new_id)

    def update_block(self, node_id: str, params: dict) -> dict[str, Any]:
        if not isinstance(params, dict) or not params:
            raise ToolError("params must be a non-empty object")
        self.node(node_id)

        def merge(graph: Graph) -> None:
            target = next(n for n in graph["nodes"] if n["id"] == node_id)
            target["params"] = {**target["params"], **params}

        self._apply(merge)
        return self.node(node_id)

    def remove_block(self, node_id: str) -> None:
        if node_id == START_ID:
            raise ToolError("the Start block cannot be removed")
        self.node(node_id)

        def drop(graph: Graph) -> None:
            graph["nodes"] = [n for n in graph["nodes"] if n["id"] != node_id]
            graph["edges"] = [e for e in graph["edges"] if node_id not in (e["source"], e["target"])]

        self._apply(drop)

    def connect(self, source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
        """Wire an output to an input. Like the editor, a new wire replaces the old one on that port."""
        source_handle = self._handle(source, source_port, outputs=True)
        target_handle = self._handle(target, target_port, outputs=False)
        edge = {"source": source, "sourceHandle": source_handle, "target": target, "targetHandle": target_handle}
        is_exec = source_handle.startswith("exec:")

        def wire(graph: Graph) -> None:
            graph["edges"] = [
                e
                for e in graph["edges"]
                if not (
                    (is_exec and (e["source"], e["sourceHandle"]) == (source, source_handle))
                    or (not is_exec and (e["target"], e["targetHandle"]) == (target, target_handle))
                )
            ]
            graph["edges"].append(edge)

        self._apply(wire)
        return edge

    def disconnect(self, source: str, target: str) -> int:
        """Remove every wire from ``source`` to ``target``. Returns how many were removed."""
        before = len(self._graph["edges"])
        self._apply(
            lambda g: g.__setitem__(
                "edges", [e for e in g["edges"] if (e["source"], e["target"]) != (source, target)]
            )
        )
        removed = before - len(self._graph["edges"])
        if removed == 0:
            raise ToolError(f"there is no connection from {source} to {target}")
        return removed

    def replace(self, graph: Graph) -> None:
        self._apply(lambda g: g.update(copy.deepcopy(graph)))

    def _apply(self, mutate: Callable[[Graph], Any]) -> None:
        draft = copy.deepcopy(self._graph)
        mutate(draft)
        try:
            self._graph = normalize_graph(draft)
        except CanvasError as exc:
            raise ToolError(str(exc)) from exc
        self.changed = True

    def _handle(self, node_id: str, port: str, *, outputs: bool) -> str:
        """Accept ``then`` as well as ``exec:then``, resolved against the block's own ports."""
        spec = BLOCKS[str(self.node(node_id)["type"])]
        handles = spec.output_handles() if outputs else spec.input_handles()
        if port in handles:
            return port
        matches = [h for h in handles if h.split(":", 1)[1] == port]
        if len(matches) == 1:
            return matches[0]
        side = "output" if outputs else "input"
        listed = ", ".join(sorted(handles)) or "none"
        raise ToolError(f"{node_id} has no {side} port {port!r}; its {side} ports are {listed}")

    def _fresh_id(self, block_type: str) -> str:
        taken = {n["id"] for n in self._graph["nodes"]}
        prefix = block_type.replace("_", "")[:12]
        return next(f"{prefix}{i}" for i in itertools.count(1) if f"{prefix}{i}" not in taken)
