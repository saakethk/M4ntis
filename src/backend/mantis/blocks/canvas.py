"""Validate and normalize block graphs exchanged with the editor and the AI assistant.

A canvas graph is ``{"nodes": [{id, type, params}], "edges": [{source,
sourceHandle, target, targetHandle}]}``. :func:`normalize_graph` accepts loose
input (missing params, lowercase tickers, ``from``/``to`` edge keys), fills
defaults, and raises :class:`CanvasError` for anything the editor could not place.
"""

from __future__ import annotations

import math
import re

from src.backend.mantis.blocks.catalog import BLOCKS, NUM_BUFFERS, Param

MAX_NODES = 80
MAX_EDGES = 160
START_ID = "start"
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,7}$")


class CanvasError(ValueError):
    """The graph cannot be placed on the canvas. The message says why."""


def empty_canvas() -> dict[str, list]:
    return normalize_graph({"nodes": [{"id": START_ID, "type": "start"}], "edges": []})


def normalize_graph(raw: object) -> dict[str, list]:
    """Return a graph the editor can apply, or raise CanvasError."""
    if not isinstance(raw, dict):
        raise CanvasError("graph must be an object")
    raw_nodes, raw_edges = raw.get("nodes"), raw.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise CanvasError("graph needs nodes and edges arrays")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise CanvasError(f"graph is too large (at most {MAX_NODES} blocks and {MAX_EDGES} connections)")

    nodes = [normalize_node(item) for item in raw_nodes]
    ids = [node["id"] for node in nodes]
    duplicate = next((node_id for node_id in ids if ids.count(node_id) > 1), None)
    if duplicate:
        raise CanvasError(f"duplicate block id {duplicate}")
    if not any(node["type"] == "start" for node in nodes):
        nodes.insert(0, normalize_node({"id": START_ID, "type": "start"}))
    nodes.sort(key=lambda node: node["type"] != "start")

    by_id = {node["id"]: node for node in nodes}
    edges = [normalize_edge(item, by_id) for item in raw_edges]
    check_edges(edges)
    if sum(node["type"] == "get_ticker" for node in nodes) > NUM_BUFFERS:
        raise CanvasError(f"a strategy can use at most {NUM_BUFFERS} Get ticker blocks")
    for node in nodes:
        if node["type"] == "for" and node["params"]["step"] == 0:
            raise CanvasError(f"{node['id']}: for step cannot be 0")
    return {"nodes": nodes, "edges": edges}


def normalize_node(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise CanvasError("each block must be an object")
    node_id, node_type = item.get("id"), item.get("type")
    if not isinstance(node_type, str) or node_type not in BLOCKS:
        raise CanvasError(f"unknown block type {node_type!r}")
    if node_type == "start":
        if node_id not in (None, START_ID):
            raise CanvasError("the Start block id must be start")
        node_id = START_ID
    if not isinstance(node_id, str) or _ID.fullmatch(node_id) is None:
        raise CanvasError(f"block id {node_id!r} is not valid (letters, digits, _ or -, starting with a letter)")
    params = item.get("params") or {}
    if not isinstance(params, dict):
        raise CanvasError(f"{node_id}: params must be an object")
    return {"id": node_id, "type": node_type, "params": normalize_params(node_type, params)}


def normalize_params(node_type: str, raw: dict) -> dict[str, object]:
    spec = BLOCKS[node_type].params
    unknown = [key for key in raw if key not in spec]
    if unknown:
        raise CanvasError(f"{node_type} has no param {unknown[0]!r}")
    filled: dict[str, object] = {}
    for key, param in spec.items():
        value = raw.get(key)
        if value is None or (value == "" and param.kind != "ticker"):
            filled[key] = param.default
        else:
            filled[key] = _coerce(node_type, key, param, value)
    return filled


def normalize_edge(item: object, nodes: dict[str, dict[str, object]]) -> dict[str, str]:
    if not isinstance(item, dict):
        raise CanvasError("each connection must be an object")
    source = item.get("source", item.get("from"))
    target = item.get("target", item.get("to"))
    source_handle = item.get("sourceHandle", item.get("source_handle"))
    target_handle = item.get("targetHandle", item.get("target_handle"))
    if not all(isinstance(part, str) for part in (source, target, source_handle, target_handle)):
        raise CanvasError("connection is missing a block or port")
    if source == target:
        raise CanvasError("a block cannot connect to itself")
    if source not in nodes or target not in nodes:
        missing = source if source not in nodes else target
        raise CanvasError(f"connection references missing block {missing}")
    source_spec = BLOCKS[str(nodes[source]["type"])]
    target_spec = BLOCKS[str(nodes[target]["type"])]
    if source_handle not in source_spec.output_handles():
        raise CanvasError(f"{source} has no output port {source_handle}")
    if target_handle not in target_spec.input_handles():
        raise CanvasError(f"{target} has no input port {target_handle}")
    if source_handle.split(":")[0] != target_handle.split(":")[0]:
        raise CanvasError("exec ports only connect to exec ports, data ports to data ports")
    return {"source": source, "sourceHandle": source_handle, "target": target, "targetHandle": target_handle}


def check_edges(edges: list[dict[str, str]]) -> None:
    """Each exec output and each data input takes one connection, and nothing forms a cycle."""
    exec_outs: set[tuple[str, str]] = set()
    data_ins: set[tuple[str, str]] = set()
    for edge in edges:
        if edge["sourceHandle"].startswith("exec:"):
            key = (edge["source"], edge["sourceHandle"])
            if key in exec_outs:
                raise CanvasError(f"{edge['source']} {edge['sourceHandle']} already has a connection")
            exec_outs.add(key)
        else:
            key = (edge["target"], edge["targetHandle"])
            if key in data_ins:
                raise CanvasError(f"{edge['target']} {edge['targetHandle']} already has a connection")
            data_ins.add(key)
    if _cyclic(edges, "exec:") or _cyclic(edges, "data:"):
        raise CanvasError("connections cannot form a cycle")


def _coerce(node_type: str, key: str, param: Param, value: object) -> object:
    if param.kind == "int":
        number = _whole(value)
        if number is None or not param.lo <= number <= param.hi:  # type: ignore[operator]
            raise CanvasError(f"{node_type} {key} must be a whole number from {param.lo:g} to {param.hi:g}")
        return number
    if param.kind == "number":
        number = _finite(value)
        if number is None or (param.lo is not None and not param.lo <= number <= param.hi):  # type: ignore[operator]
            raise CanvasError(f"{node_type} {key} is out of range")
        return int(number) if number.is_integer() else number
    if param.kind == "choice":
        if value not in param.choices:
            raise CanvasError(f"{node_type} {key} must be one of {', '.join(map(str, param.choices))}")
        return value
    if not isinstance(value, str):
        raise CanvasError(f"{node_type} {key} must be a ticker symbol")
    ticker = value.strip().upper()
    if ticker and _TICKER.fullmatch(ticker) is None:
        raise CanvasError(f"{node_type} {key} is not a ticker symbol")
    return ticker


def _cyclic(edges: list[dict[str, str]], prefix: str) -> bool:
    adjacent: dict[str, list[str]] = {}
    for edge in edges:
        if edge["sourceHandle"].startswith(prefix):
            adjacent.setdefault(edge["source"], []).append(edge["target"])
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> bool:
        visiting.add(node)
        for nxt in adjacent.get(node, []):
            if nxt in visiting or (nxt not in done and visit(nxt)):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    return any(node not in done and visit(node) for node in list(adjacent))


def _whole(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _finite(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None
