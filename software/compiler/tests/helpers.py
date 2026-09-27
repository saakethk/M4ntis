from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradecpu.isa import IMPLEMENTED, Instr  # noqa: E402

DEFAULTS = {
    "start": {"startingBalance": 100000, "resolution": "5m", "symbol0": "AAPL",
              "symbol1": "", "symbol2": "", "symbol3": "", "symbol4": ""},
    "current_price": {"buffer": 0},
    "get_ticker": {"symbol": "AAPL"},
    "sum_n_ticks": {"buffer": 0, "n": 5},
    "price_n_ticks_ago": {"buffer": 0, "n": 1},
    "constant": {"value": 0},
    "set_var": {"slot": "VAR1"},
    "get_var": {"slot": "VAR1"},
    "power": {"exponent": 2},
    "if": {"operator": ">"},
    "for": {"start": 0, "end": 3, "step": 1},
    "buy": {"buffer": 0, "quantity": 10},
    "sell": {"buffer": 0, "quantity": 10},
    "sma": {"buffer": 0, "n": 5},
    "momentum": {"buffer": 0, "n": 3},
    "volatility": {"buffer": 0, "n": 5},
    "mean_reversion_bands": {"buffer": 0, "n": 5, "k": 2},
}


class Doc:
    """Tiny builder for m4ntis.strategy/v1 documents."""

    def __init__(self, name: str = "test", **start_params):
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.add("start", "start", **start_params)

    def add(self, nid: str, ntype: str, **params) -> str:
        p = {**DEFAULTS.get(ntype, {}), **params}
        self.nodes.append({"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"params": p}})
        return nid

    def exec(self, src: str, dst: str, port: str = "out") -> "Doc":
        self.edges.append({"id": f"{src}.{port}-{dst}", "source": src, "sourceHandle": f"exec:{port}",
                           "target": dst, "targetHandle": "exec:in", "data": {"kind": "exec"}})
        return self

    def data(self, src: str, dst: str, dst_port: str, src_port: str = "out") -> "Doc":
        self.edges.append({"id": f"{src}.{src_port}-{dst}.{dst_port}", "source": src,
                           "sourceHandle": f"data:{src_port}", "target": dst,
                           "targetHandle": f"data:{dst_port}", "data": {"kind": "data"}})
        return self

    def json(self) -> dict:
        return {"schema": "m4ntis.strategy/v1", "name": "test", "savedAt": "",
                "flow": {"nodes": self.nodes, "edges": self.edges}}


def only_rtl_ops(items) -> bool:
    return all(it.op in IMPLEMENTED for it in items if isinstance(it, Instr))
