"""Block catalog as the compiler sees it: ports and parameter constraints.

Mirrors src/frontend/src/blocks/catalog.ts; tests/test_catalog_sync.py
checks the two stay in step via the frontend's exported examples/block_catalog.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .isa import BUFFER_DEPTH, NUM_BUFFERS, NUM_VARS

RESOLUTIONS: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 390}


@dataclass(frozen=True)
class Param:
    kind: str  # "int" | "number" | "choice" | "symbol"
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    required: bool = True


@dataclass(frozen=True)
class BlockSpec:
    exec_in: bool = False
    exec_outs: tuple[str, ...] = ()
    data_ins: tuple[str, ...] = ()
    data_outs: tuple[str, ...] = ()
    params: dict[str, Param] = field(default_factory=dict)
    # Ticks of buffer history needed, as a function of params (0 = none).
    history: str | None = None


BUFFER = Param("int", 0, NUM_BUFFERS - 1)
SLOT = Param("choice", choices=tuple(f"VAR{i}" for i in range(1, NUM_VARS + 1)))
QTY = Param("int", 1, 32767)
# GETSUMPRICEBEFORE sums offsets 0..N-1, so N may be the full depth.
WINDOW = Param("int", 1, BUFFER_DEPTH)
# GETSTOCKPRICEBEFORE offset 30 aliases to offset 0 (mod 30), so 29 is the furthest back.
OFFSET = Param("int", 1, BUFFER_DEPTH - 1)
VOL_WINDOW = Param("int", 2, BUFFER_DEPTH)
OPERATORS = (">", ">=", "<", "<=", "==", "!=")

_START_PARAMS: dict[str, Param] = {
    "startingBalance": Param("number", 0, 21_000_000),
    "resolution": Param("choice", choices=tuple(RESOLUTIONS)),
    **{f"symbol{i}": Param("symbol", required=False) for i in range(NUM_BUFFERS)},
}

BLOCKS: dict[str, BlockSpec] = {
    "start": BlockSpec(exec_outs=("out",), params=_START_PARAMS),
    "current_price": BlockSpec(data_outs=("out",), params={"buffer": BUFFER}, history="1"),
    "sum_n_ticks": BlockSpec(data_outs=("out",), params={"buffer": BUFFER, "n": WINDOW}, history="n"),
    "price_n_ticks_ago": BlockSpec(
        data_outs=("out",), params={"buffer": BUFFER, "n": OFFSET}, history="n+1"
    ),
    "constant": BlockSpec(data_outs=("out",), params={"value": Param("number")}),
    "set_var": BlockSpec(
        exec_in=True, exec_outs=("out",), data_ins=("value",), params={"slot": SLOT}
    ),
    "get_var": BlockSpec(data_outs=("out",), params={"slot": SLOT}),
    "get_balance": BlockSpec(data_outs=("out",)),
    "add": BlockSpec(data_ins=("a", "b"), data_outs=("out",)),
    "subtract": BlockSpec(data_ins=("a", "b"), data_outs=("out",)),
    "multiply": BlockSpec(data_ins=("a", "b"), data_outs=("out",)),
    "divide": BlockSpec(data_ins=("a", "b"), data_outs=("out",)),
    "power": BlockSpec(data_ins=("base",), data_outs=("out",), params={"exponent": Param("int", 0, 8)}),
    "sqrt": BlockSpec(data_ins=("x",), data_outs=("out",)),
    "log": BlockSpec(data_ins=("x", "base"), data_outs=("out",)),
    "if": BlockSpec(
        exec_in=True,
        exec_outs=("then", "else"),
        data_ins=("a", "b"),
        params={"operator": Param("choice", choices=OPERATORS)},
    ),
    "for": BlockSpec(
        exec_in=True,
        exec_outs=("body", "after"),
        data_outs=("index",),
        params={
            "start": Param("int", -32768, 32767),
            "end": Param("int", -32768, 32767),
            "step": Param("int", -32768, 32767),
        },
    ),
    # Trades read the current price to charge the balance.
    "buy": BlockSpec(
        exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QTY}, history="1"
    ),
    "sell": BlockSpec(
        exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QTY}, history="1"
    ),
    "sma": BlockSpec(data_outs=("out",), params={"buffer": BUFFER, "n": WINDOW}, history="n"),
    "momentum": BlockSpec(data_outs=("out",), params={"buffer": BUFFER, "n": OFFSET}, history="n+1"),
    "volatility": BlockSpec(data_outs=("out",), params={"buffer": BUFFER, "n": VOL_WINDOW}, history="n"),
    "mean_reversion_bands": BlockSpec(
        data_outs=("upper", "middle", "lower"),
        params={"buffer": BUFFER, "n": VOL_WINDOW, "k": Param("number", 0, 10)},
        history="n",
    ),
}

# Blocks with no possible lowering onto this ISA.
UNSUPPORTED: dict[str, str] = {
    "log": "Log has no opcode and no practical integer expansion on this ISA",
}


def history_ticks(spec: BlockSpec, params: dict) -> int:
    if spec.history is None:
        return 0
    if spec.history == "1":
        return 1
    n = int(params["n"])
    return n + 1 if spec.history == "n+1" else n
