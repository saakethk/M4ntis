"""Composite blocks that the backend rewrites into compiler blocks before compiling.

A macro block exists in the editor and the assistant catalog but not in the
TradeCPU compiler. :func:`expand_document` replaces every macro node in a
``m4ntis.strategy/v1`` document with a small subgraph of blocks the compiler
already lowers. Generated nodes are named ``<macro id>::<part>``, so a compiler
diagnostic on a generated node can be pointed back at the block the user placed
(:func:`source_node`).

Adding a macro is one function that returns a :class:`Expansion`, registered in
``MACROS`` (plus the catalog entries in the backend and the editor).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SEPARATOR = "::"


@dataclass(frozen=True)
class Part:
    name: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Expansion:
    parts: tuple[Part, ...]
    # (source part, source handle, target part, target handle)
    wires: tuple[tuple[str, str, str, str], ...]
    # Macro output handle -> (part, handle) that produces it.
    outputs: dict[str, tuple[str, str]]
    # Macro input handle -> every (part, handle) it feeds.
    inputs: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)


def _z_score(params: dict[str, Any]) -> Expansion:
    """(price - SMA_n) / volatility_n. The hardware returns 0 when volatility is 0."""
    buffer, n = params.get("buffer", 0), params.get("n", 20)
    return Expansion(
        parts=(
            Part("price", "current_price", {"buffer": buffer}),
            Part("mean", "sma", {"buffer": buffer, "n": n}),
            Part("spread", "subtract"),
            Part("stdev", "volatility", {"buffer": buffer, "n": n}),
            Part("ratio", "divide"),
        ),
        wires=(
            ("price", "data:out", "spread", "data:a"),
            ("mean", "data:out", "spread", "data:b"),
            ("spread", "data:out", "ratio", "data:a"),
            ("stdev", "data:out", "ratio", "data:b"),
        ),
        outputs={"data:out": ("ratio", "data:out")},
    )


MACROS: dict[str, Callable[[dict[str, Any]], Expansion]] = {
    "z_score": _z_score,
}


def source_node(node_id: str | None) -> str | None:
    """The user-placed block a (possibly generated) node id came from."""
    return None if node_id is None else node_id.split(SEPARATOR, 1)[0]


def expand_document(document: dict[str, Any]) -> dict[str, Any]:
    """A copy of the document with every macro node replaced by its expansion."""
    flow = document.get("flow")
    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        return document
    nodes: list[Any] = []
    edges: list[Any] = [edge for edge in flow.get("edges") or [] if isinstance(edge, dict)]
    expansions: dict[str, Expansion] = {}
    for node in flow["nodes"]:
        build = MACROS.get(node.get("type")) if isinstance(node, dict) else None
        if build is None:
            nodes.append(node)
            continue
        macro_id = str(node.get("id"))
        params = ((node.get("data") or {}).get("params")) or {}
        expansion = build(params)
        expansions[macro_id] = expansion
        position = node.get("position") or {"x": 0, "y": 0}
        for part in expansion.parts:
            nodes.append(
                {
                    "id": _part_id(macro_id, part.name),
                    "type": part.type,
                    "position": position,
                    "data": {"params": dict(part.params)},
                }
            )
        for src, src_handle, dst, dst_handle in expansion.wires:
            edges.append(_edge(_part_id(macro_id, src), src_handle, _part_id(macro_id, dst), dst_handle))
    if not expansions:
        return document
    rewired: list[dict[str, Any]] = []
    for edge in edges:
        rewired.extend(_rewire(edge, expansions))
    expanded = copy.deepcopy(document)
    expanded["flow"] = {**flow, "nodes": nodes, "edges": rewired}
    return expanded


def _rewire(edge: dict[str, Any], expansions: dict[str, Expansion]) -> list[dict[str, Any]]:
    source, target = str(edge.get("source")), str(edge.get("target"))
    source_handle, target_handle = str(edge.get("sourceHandle")), str(edge.get("targetHandle"))
    if source in expansions:
        produced = expansions[source].outputs.get(source_handle)
        if produced is None:
            return []
        source, source_handle = _part_id(source, produced[0]), produced[1]
    targets = [(target, target_handle)]
    if target in expansions:
        fed = expansions[target].inputs.get(target_handle, ())
        targets = [(_part_id(target, part), handle) for part, handle in fed]
    return [_edge(source, source_handle, tgt, tgt_handle) for tgt, tgt_handle in targets]


def _part_id(macro_id: str, part: str) -> str:
    return f"{macro_id}{SEPARATOR}{part}"


def _edge(source: str, source_handle: str, target: str, target_handle: str) -> dict[str, Any]:
    return {
        "id": f"e_{source}.{source_handle}__{target}.{target_handle}",
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
        "data": {"kind": source_handle.split(":")[0]},
    }
