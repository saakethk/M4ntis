"""The block catalog as the backend sees it: ports, parameters, and descriptions.

This mirrors ``integration/software/src/blocks/catalog.ts`` (the editor's catalog)
and the compiler's catalog in ``software/compiler/tradecpu/blocks.py``. Blocks
marked ``macro`` are not known to the compiler; :mod:`mantis.blocks.macros`
rewrites them into compiler blocks before compiling.

Port handles are ``exec:<name>`` or ``data:<name>``, the same ids the editor uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NUM_BUFFERS = 5
NUM_VAR_SLOTS = 15
BUFFER_DEPTH = 30
RESOLUTIONS = ("1m", "5m", "15m", "30m", "1h", "1d")
OPERATORS = (">", ">=", "<", "<=", "==", "!=")
SLOTS = tuple(f"VAR{i}" for i in range(1, NUM_VAR_SLOTS + 1))


@dataclass(frozen=True)
class Param:
    kind: str  # int | number | choice | ticker
    default: object
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()

    def describe(self, key: str) -> str:
        if self.kind == "int":
            return f"{key} int {self.lo:g}..{self.hi:g} (default {self.default})"
        if self.kind == "number":
            span = "" if self.lo is None else f" {self.lo:g}..{self.hi:g}"
            return f"{key} number{span} (default {self.default})"
        if self.kind == "choice":
            return f"{key} one of {'|'.join(map(str, self.choices))} (default {self.default})"
        return f"{key} ticker symbol or empty"


@dataclass(frozen=True)
class Block:
    label: str
    description: str
    exec_in: bool = False
    exec_outs: tuple[str, ...] = ()
    data_ins: tuple[str, ...] = ()
    data_outs: tuple[str, ...] = ()
    params: dict[str, Param] = field(default_factory=dict)
    macro: bool = False

    def handles(self) -> dict[str, str]:
        """Every port handle on this block mapped to its kind (``exec`` or ``data``)."""
        found = {"exec:in": "exec"} if self.exec_in else {}
        found.update({f"exec:{name}": "exec" for name in self.exec_outs})
        found.update({f"data:{name}": "data" for name in (*self.data_ins, *self.data_outs)})
        return found

    def input_handles(self) -> set[str]:
        return ({"exec:in"} if self.exec_in else set()) | {f"data:{name}" for name in self.data_ins}

    def output_handles(self) -> set[str]:
        return {f"exec:{name}" for name in self.exec_outs} | {f"data:{name}" for name in self.data_outs}

    def describe(self, block_type: str) -> str:
        ports = ", ".join(self.handles()) or "none"
        params = ", ".join(p.describe(k) for k, p in self.params.items()) or "none"
        return f"- {block_type} ({self.label}): {self.description} Ports {ports}; params {params}"


def _int(lo: int, hi: int, default: int) -> Param:
    return Param("int", default, lo, hi)


BUFFER = _int(0, NUM_BUFFERS - 1, 0)
WINDOW = _int(1, BUFFER_DEPTH, 20)
OFFSET = _int(1, BUFFER_DEPTH - 1, 10)
VOL_WINDOW = _int(2, BUFFER_DEPTH, 20)
QUANTITY = _int(1, 32767, 10)
IMM16 = (-32768, 32767)

BLOCKS: dict[str, Block] = {
    "start": Block(
        "Start",
        "Runs the graph once per tick; sets balance, resolution, and legacy stock slots.",
        exec_outs=("out",),
        params={
            "startingBalance": Param("number", 100000, 0, 21_000_000),
            "resolution": Param("choice", "5m", choices=RESOLUTIONS),
            **{f"symbol{i}": Param("ticker", "") for i in range(NUM_BUFFERS)},
        },
    ),
    "get_ticker": Block(
        "Get ticker",
        "Current price of one stock. Fills the next stock slot BUF0..BUF4 in id order.",
        data_outs=("out",),
        params={"symbol": Param("ticker", "AAPL"), "buffer": BUFFER},
    ),
    "sum_n_ticks": Block(
        "Sum of Last N Ticks",
        "Sum of the N most recent prices of a stock slot.",
        data_outs=("out",),
        params={"buffer": BUFFER, "n": WINDOW},
    ),
    "price_n_ticks_ago": Block(
        "Price N Ticks Ago",
        "Price of a stock slot N ticks before now.",
        data_outs=("out",),
        params={"symbol": Param("ticker", ""), "buffer": BUFFER, "n": OFFSET},
    ),
    "constant": Block("Constant", "A literal number (prices are dollars).", data_outs=("out",), params={"value": Param("number", 0)}),
    "set_var": Block(
        "Set Variable",
        "Store a value in a variable slot; values persist between ticks.",
        exec_in=True,
        exec_outs=("out",),
        data_ins=("value",),
        params={"slot": Param("choice", "VAR1", choices=SLOTS)},
    ),
    "get_var": Block("Get Variable", "Read a variable slot.", data_outs=("out",), params={"slot": Param("choice", "VAR1", choices=SLOTS)}),
    "add": Block("Add", "A + B.", data_ins=("a", "b"), data_outs=("out",)),
    "subtract": Block("Subtract", "A - B.", data_ins=("a", "b"), data_outs=("out",)),
    "multiply": Block("Multiply", "A x B.", data_ins=("a", "b"), data_outs=("out",)),
    "divide": Block("Divide", "A / B to 2 decimals (0 when B is 0).", data_ins=("a", "b"), data_outs=("out",)),
    "power": Block("Power", "base ^ exponent.", data_ins=("base",), data_outs=("out",), params={"exponent": _int(0, 8, 2)}),
    "sqrt": Block("Square Root", "Square root of x.", data_ins=("x",), data_outs=("out",)),
    "if": Block(
        "If / Else",
        "Compare A with B and continue on Then or Else.",
        exec_in=True,
        exec_outs=("then", "else"),
        data_ins=("a", "b"),
        params={"operator": Param("choice", ">", choices=OPERATORS)},
    ),
    "for": Block(
        "For (Range)",
        "Run Body for each i in [start, end) within one tick, then After.",
        exec_in=True,
        exec_outs=("body", "after"),
        data_outs=("index",),
        params={"start": _int(*IMM16, 0), "end": _int(*IMM16, 10), "step": _int(*IMM16, 1)},
    ),
    "buy": Block("Buy", "Buy shares of a stock slot at the current price.", exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QUANTITY}),
    "sell": Block("Sell", "Sell shares of a stock slot at the current price.", exec_in=True, exec_outs=("out",), params={"buffer": BUFFER, "quantity": QUANTITY}),
    "sma": Block("SMA", "Simple moving average over N ticks.", data_outs=("out",), params={"buffer": BUFFER, "n": WINDOW}),
    "momentum": Block("Momentum", "Fractional change over N ticks (0.05 = up 5%).", data_outs=("out",), params={"buffer": BUFFER, "n": OFFSET}),
    "volatility": Block("Volatility", "Standard deviation of price over N ticks.", data_outs=("out",), params={"buffer": BUFFER, "n": VOL_WINDOW}),
    "mean_reversion_bands": Block(
        "Mean Reversion Bands",
        "SMA plus and minus k standard deviations.",
        data_outs=("upper", "middle", "lower"),
        params={"buffer": BUFFER, "n": VOL_WINDOW, "k": Param("number", 2, 0, 10)},
    ),
    "z_score": Block(
        "Z-Score",
        "How many standard deviations the price is from its N-tick SMA (0 on flat prices).",
        data_outs=("out",),
        params={"buffer": BUFFER, "n": VOL_WINDOW},
        macro=True,
    ),
}


def catalog_for_prompt() -> str:
    """One line per block: what it does and the ports and params the model may use."""
    return "\n".join(spec.describe(name) for name, spec in BLOCKS.items())
