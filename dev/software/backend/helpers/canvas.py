"""Canvas graphs the assistant can place on the strategy editor.

A graph is nodes plus edges. Block types, ports, and parameter ranges match the
editor catalog. Get ticker blocks fill BUF0 onward in alphabetical node-id order,
which is the same rule the compiler uses.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

MAX_NODES = 80
MAX_EDGES = 160
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,7}$")
RESOLUTIONS = ("1m", "5m", "15m", "30m", "1h", "1d")
OPERATORS = (">", ">=", "<", "<=", "==", "!=")
SLOTS = tuple(f"VAR{i}" for i in range(1, 16))


class CanvasError(ValueError):
    """The graph cannot be placed on the canvas."""


@dataclass(frozen=True)
class Param:
    kind: str  # int | number | choice | ticker | symbol
    default: object
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    required: bool = False


@dataclass(frozen=True)
class Block:
    exec_in: bool = False
    exec_outs: tuple[str, ...] = ()
    data_ins: tuple[str, ...] = ()
    data_outs: tuple[str, ...] = ()
    params: dict[str, Param] | None = None

    def handles(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if self.exec_in:
            found["exec:in"] = "exec"
        for name in self.exec_outs:
            found[f"exec:{name}"] = "exec"
        for name in self.data_ins:
            found[f"data:{name}"] = "data"
        for name in self.data_outs:
            found[f"data:{name}"] = "data"
        return found


def _int(lo: float, hi: float, default: int) -> Param:
    return Param("int", default, lo, hi)


def _choice(choices: tuple, default: object) -> Param:
    return Param("choice", default, choices=choices)


BUFFER = _int(0, 4, 0)
WINDOW = _int(1, 30, 20)
OFFSET = _int(1, 29, 10)
VOL = _int(2, 30, 20)
QTY = _int(1, 32767, 10)

BLOCKS: dict[str, Block] = {
    "start": Block(
        exec_outs=("out",),
        params={
            "startingBalance": Param("number", 100000, 0, 21_000_000),
            "resolution": _choice(RESOLUTIONS, "5m"),
            **{f"symbol{i}": Param("symbol", "") for i in range(5)},
        },
    ),
    "get_ticker": Block(
        data_outs=("out",),
        params={"symbol": Param("ticker", "AAPL"), "buffer": BUFFER},
    ),
    "sum_n_ticks": Block(data_outs=("out",), params={"buffer": BUFFER, "n": WINDOW}),
    "price_n_ticks_ago": Block(
        data_outs=("out",),
        params={"symbol": Param("symbol", ""), "buffer": BUFFER, "n": OFFSET},
    ),
    "constant": Block(data_outs=("out",), params={"value": Param("number", 0)}),
    "set_var": Block(exec_in=True, exec_outs=("out",), data_ins=("value",), params={"slot": _choice(SLOTS, "VAR1")}),
    "get_var": Block(data_outs=("out",), params={"slot": _choice(SLOTS, "VAR1")}),
    "add": Block(data_ins=("a", "b"), data_outs=("out",)),
    "subtract": Block(data_ins=("a", "b"), data_outs=("out",)),
    "multiply": Block(data_ins=("a", "b"), data_outs=("out",)),
    "divide": Block(data_ins=("a", "b"), data_outs=("out",)),
    "power": Block(data_ins=("base",), data_outs=("out",), params={"exponent": _int(0, 8, 2)}),
    "sqrt": Block(data_ins=("x",), data_outs=("out",)),
    "if": Block(
        exec_in=True,
        exec_outs=("then", "else"),
        data_ins=("a", "b"),
        params={"operator": _choice(OPERATORS, ">")},
    ),
    "for": Block(
        exec_in=True,
        exec_outs=("body", "after"),
        data_outs=("index",),
        params={"start": _int(-32768, 32767, 0), "end": _int(-32768, 32767, 10), "step": _int(-32768, 32767, 1)},
    ),
    "buy": Block(exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QTY}),
    "sell": Block(exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QTY}),
    "sma": Block(data_outs=("out",), params={"buffer": BUFFER, "n": WINDOW}),
    "momentum": Block(data_outs=("out",), params={"buffer": BUFFER, "n": OFFSET}),
    "volatility": Block(data_outs=("out",), params={"buffer": BUFFER, "n": VOL}),
    "mean_reversion_bands": Block(
        data_outs=("upper", "middle", "lower"),
        params={"buffer": BUFFER, "n": VOL, "k": Param("number", 2, 0, 10)},
    ),
}


def catalog_for_prompt() -> str:
    """One line per block: ports and parameters the model is allowed to emit."""
    lines = []
    for name, spec in BLOCKS.items():
        ports = ", ".join(spec.handles()) or "none"
        params = spec.params or {}
        if params:
            described = ", ".join(_describe(key, param) for key, param in params.items())
        else:
            described = "none"
        lines.append(f"- {name}: ports {ports}; params {described}")
    return "\n".join(lines)


def empty_canvas() -> dict[str, list]:
    return normalize_graph({"nodes": [{"id": "start", "type": "start", "params": {}}], "edges": []})


def normalize_graph(raw: object) -> dict[str, list]:
    """Return a graph the editor can apply, or raise CanvasError."""
    if not isinstance(raw, dict):
        raise CanvasError("graph must be an object")
    raw_nodes = raw.get("nodes")
    raw_edges = raw.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise CanvasError("graph needs nodes and edges arrays")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise CanvasError("graph is too large")

    nodes: list[dict[str, object]] = []
    seen: set[str] = set()
    start_count = 0
    for item in raw_nodes:
        node = _node(item)
        if node["id"] in seen:
            raise CanvasError(f"duplicate node id {node['id']}")
        seen.add(str(node["id"]))
        if node["type"] == "start":
            start_count += 1
            node["id"] = "start"
        nodes.append(node)
    if start_count > 1:
        raise CanvasError("only one Start block is allowed")
    if start_count == 0:
        nodes.insert(0, _node({"id": "start", "type": "start", "params": {}}))
    else:
        nodes.sort(key=lambda node: node["type"] != "start")

    by_id = {str(node["id"]): node for node in nodes}
    edges: list[dict[str, str]] = []
    exec_outs: set[tuple[str, str]] = set()
    data_ins: set[tuple[str, str]] = set()
    for item in raw_edges:
        edge = _edge(item, by_id)
        key_out = (edge["source"], edge["sourceHandle"])
        key_in = (edge["target"], edge["targetHandle"])
        if edge["sourceHandle"].startswith("exec:"):
            if key_out in exec_outs:
                raise CanvasError(f"{edge['source']} {edge['sourceHandle']} already has an exec edge")
            exec_outs.add(key_out)
        else:
            if key_in in data_ins:
                raise CanvasError(f"{edge['target']} {edge['targetHandle']} already has a data edge")
            data_ins.add(key_in)
        edges.append(edge)
    tickers = [node for node in nodes if node["type"] == "get_ticker"]
    if len(tickers) > 5:
        raise CanvasError("a strategy can use at most five Get ticker blocks")
    if _cyclic(edges, "exec") or _cyclic(edges, "data"):
        raise CanvasError("connections cannot form a cycle")
    for node in nodes:
        if node["type"] == "for" and node["params"].get("step") == 0:  # type: ignore[union-attr]
            raise CanvasError("for step cannot be 0")
    return {"nodes": nodes, "edges": edges}


def _describe(key: str, param: Param) -> str:
    if param.kind == "int":
        return f"{key} int {param.lo:g}..{param.hi:g} (default {param.default})"
    if param.kind == "number":
        span = "" if param.lo is None else f" {param.lo:g}..{param.hi:g}"
        return f"{key} number{span} (default {param.default})"
    if param.kind == "choice":
        return f"{key} one of {'|'.join(map(str, param.choices))}"
    return f"{key} ticker or empty"


def _node(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise CanvasError("each node must be an object")
    node_id = item.get("id")
    node_type = item.get("type")
    if not isinstance(node_id, str) or _ID.fullmatch(node_id) is None:
        raise CanvasError("node id is not valid")
    if not isinstance(node_type, str) or node_type not in BLOCKS:
        raise CanvasError(f"unknown block {node_type!r}")
    if node_type == "start" and node_id != "start":
        raise CanvasError("the Start block id must be start")
    params = item.get("params", {})
    if not isinstance(params, dict):
        raise CanvasError(f"{node_id} params must be an object")
    return {"id": "start" if node_type == "start" else node_id, "type": node_type, "params": _params(node_type, params)}


def _params(node_type: str, raw: dict) -> dict[str, object]:
    spec = BLOCKS[node_type].params or {}
    unknown = [key for key in raw if key not in spec]
    if unknown:
        raise CanvasError(f"{node_type} has unknown param {unknown[0]}")
    filled: dict[str, object] = {}
    for key, param in spec.items():
        if key not in raw or raw[key] is None:
            if param.required:
                raise CanvasError(f"{node_type} is missing {key}")
            filled[key] = param.default
            continue
        if raw[key] == "":
            if param.kind in {"symbol", "ticker"} and not param.required:
                filled[key] = ""
                continue
            if param.required:
                raise CanvasError(f"{node_type} is missing {key}")
            filled[key] = param.default
            continue
        filled[key] = _coerce(node_type, key, param, raw[key])
    return filled


def _coerce(node_type: str, key: str, param: Param, value: object) -> object:
    if param.kind == "int":
        number = _whole(value)
        if number is None or param.lo is None or not param.lo <= number <= param.hi:  # type: ignore[operator]
            raise CanvasError(f"{node_type} {key} is out of range")
        return number
    if param.kind == "number":
        number = _finite(value)
        if number is None or (param.lo is not None and not param.lo <= number <= param.hi):  # type: ignore[operator]
            raise CanvasError(f"{node_type} {key} is out of range")
        return int(number) if number.is_integer() else number
    if param.kind == "choice":
        if value not in param.choices:
            raise CanvasError(f"{node_type} {key} is not allowed")
        return value
    if not isinstance(value, str):
        raise CanvasError(f"{node_type} {key} must be a ticker")
    ticker = value.strip().upper()
    if ticker == "" and param.kind in {"symbol", "ticker"} and not param.required:
        return ""
    if _TICKER.fullmatch(ticker) is None:
        raise CanvasError(f"{node_type} {key} is not a ticker")
    return ticker


def _edge(item: object, nodes: dict[str, dict[str, object]]) -> dict[str, str]:
    if not isinstance(item, dict):
        raise CanvasError("each edge must be an object")
    source = item.get("source", item.get("from"))
    target = item.get("target", item.get("to"))
    source_handle = item.get("sourceHandle", item.get("source_handle"))
    target_handle = item.get("targetHandle", item.get("target_handle"))
    if not all(isinstance(part, str) for part in (source, target, source_handle, target_handle)):
        raise CanvasError("edge is missing a port")
    if source == target:
        raise CanvasError("a block cannot connect to itself")
    if source not in nodes or target not in nodes:
        raise CanvasError("edge references a missing block")
    source_ports = BLOCKS[str(nodes[source]["type"])].handles()
    target_ports = BLOCKS[str(nodes[target]["type"])].handles()
    if source_handle not in source_ports or target_handle not in target_ports:
        raise CanvasError(f"edge uses a port {source}.{source_handle} does not have")
    if source_ports[source_handle] != target_ports[target_handle]:
        raise CanvasError("exec ports only connect to exec ports")
    if not source_handle.startswith(("exec:", "data:")) or not target_handle.startswith(("exec:", "data:")):
        raise CanvasError("edge uses a port the block does not have")
    return {
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _cyclic(edges: list[dict[str, str]], kind: str) -> bool:
    prefix = f"{kind}:"
    adjacent: dict[str, list[str]] = {}
    for edge in edges:
        if not edge["sourceHandle"].startswith(prefix):
            continue
        adjacent.setdefault(edge["source"], []).append(edge["target"])
        adjacent.setdefault(edge["target"], [])
    color: dict[str, int] = {}

    def visit(node: str) -> bool:
        color[node] = 1
        for nxt in adjacent.get(node, []):
            state = color.get(nxt, 0)
            if state == 1 or (state == 0 and visit(nxt)):
                return True
        color[node] = 2
        return False

    return any(color.get(node, 0) == 0 and visit(node) for node in adjacent)


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
    if isinstance(value, bool) or isinstance(value, str):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None
