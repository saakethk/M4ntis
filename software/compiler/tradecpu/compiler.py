"""Strategy document (m4ntis.strategy/v1, from the React Flow editor) -> TradeCPU assembly.

Program shape:

    prologue   SETBALANCE start cash, EMITBALANCE (load handshake)
    warm-up    (history-1) x [UPDATEALLSTOCKBUFFERS, EMITBALANCE]
    TICK:      UPDATEALLSTOCKBUFFERS
               <exec chain from Start>
    TICK_END:  EMITBALANCE (per-tick ack), JMP TICK

Every exec dead end jumps to TICK_END (or, inside a For body, to the loop step).
Exactly one EMIT_BALANCE message is sent per tick round; the host must wait for it
before sending the next round because each buffer stages only one pending tick.

Numbers are fixed-point: every value carries a decimal scale s (value = real * 10^s).
Prices arrive at their buffer's price exponent (2 = cents); balance is kept in cents.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .asm import Assembled, assemble, format_asm, peephole
from .blocks import BLOCKS, RESOLUTIONS, UNSUPPORTED, BlockSpec, history_ticks
from .isa import (
    IMM16_MAX,
    IMM16_MIN,
    INT32_MAX,
    INT32_MIN,
    NOT_IN_RTL,
    NUM_BUFFERS,
    NUM_REGS,
    NUM_VARS,
    Instr,
    Item,
    Label,
    Op,
)

DOCUMENT_SCHEMA = "m4ntis.strategy/v1"
COMPILED_SCHEMA = "m4ntis.compiled/v1"
MAX_SCALE = 4
BALANCE_EXP = 2
DIV_RESULT_SCALE = 2  # spec section 2: pre-multiply by 100 before dividing


@dataclass
class Diagnostic:
    level: str  # "error" | "warning"
    message: str
    node: str | None = None

    def to_json(self) -> dict:
        return {"level": self.level, "message": self.message, **({"node": self.node} if self.node else {})}

    def __str__(self) -> str:
        return f"{self.level}: {self.message}" + (f" [{self.node}]" if self.node else "")


class CompileError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(d) for d in diagnostics))


@dataclass
class CompileOptions:
    """Host-side facts the strategy document doesn't carry.

    price_exponents: per buffer, how prices are scaled into the 16-bit TICK field
    (2 = cents, 1 = dimes, 0 = whole dollars). The backtester picks this per symbol so
    the highest price in the window fits in int16 (max 32767); e.g. a $900 stock can't
    be sent in cents and must use exponent 1.
    """

    price_exponents: dict[int, int] = field(default_factory=lambda: {b: 2 for b in range(NUM_BUFFERS)})


@dataclass
class CompileResult:
    items: list[Item]
    assembled: Assembled
    manifest: dict
    warnings: list[Diagnostic]

    @property
    def asm(self) -> str:
        return format_asm(self.items)

    @property
    def words(self) -> list[int]:
        return self.assembled.words


# --------------------------------------------------------------------------- expressions


@dataclass(frozen=True)
class Const:
    value: int
    scale: int


@dataclass(frozen=True)
class Price:
    buf: int
    offset: int


@dataclass(frozen=True)
class Sum:
    buf: int
    n: int


@dataclass(frozen=True)
class VarRef:
    slot: int  # var_id 0..14


@dataclass(frozen=True)
class Bin:
    op: str  # add | sub | mul | div
    a: "Expr"
    b: "Expr"


@dataclass(frozen=True)
class Sqrt:
    x: "Expr"


@dataclass(frozen=True)
class Volatility:
    buf: int
    n: int


Expr = Const | Price | Sum | VarRef | Bin | Sqrt | Volatility


def to_fixed(value: float) -> tuple[Const, bool]:
    """Smallest decimal scale (<= MAX_SCALE) that represents value exactly; bool = was rounded."""
    for s in range(MAX_SCALE + 1):
        scaled = value * 10**s
        if abs(scaled - round(scaled)) < 1e-9:
            return Const(int(round(scaled)), s), False
    return Const(int(round(value * 10**MAX_SCALE)), MAX_SCALE), True


def _even_at_least_4(s: int) -> int:
    return max(s + (s % 2), 4)


def div_scales(sa: int, sb: int) -> tuple[int, int]:
    """(result scale, k) where the numerator is multiplied by 10^k (k<0: result divided by 10^-k)."""
    r = min(max(DIV_RESULT_SCALE, sa - sb), MAX_SCALE)
    return r, r - sa + sb


# --------------------------------------------------------------------------- graph


@dataclass
class GNode:
    id: str
    type: str
    params: dict
    spec: BlockSpec


class Strategy:
    """Validated graph built from a strategy document."""

    def __init__(self, doc: dict, options: CompileOptions):
        self.errors: list[Diagnostic] = []
        self.warnings: list[Diagnostic] = []
        self.options = options
        if not isinstance(doc, dict) or doc.get("schema") != DOCUMENT_SCHEMA:
            raise CompileError([Diagnostic("error", f"expected a {DOCUMENT_SCHEMA} document")])
        self.name = str(doc.get("name") or "Untitled strategy")
        flow = doc.get("flow") or {}

        self.nodes: dict[str, GNode] = {}
        for raw in flow.get("nodes", []):
            nid, ntype = str(raw.get("id")), raw.get("type")
            if ntype not in BLOCKS and ntype != "get_ticker":
                self.err(f"unknown block type {ntype!r}", nid)
                continue
            if nid in self.nodes:
                self.err("duplicate node id", nid)
                continue
            params = dict((raw.get("data") or {}).get("params") or {})
            if ntype == "get_ticker":
                # Same lowering as current_price. The symbol is copied onto Start below.
                self.nodes[nid] = GNode(nid, ntype, params, BLOCKS["current_price"])
                continue
            self.nodes[nid] = GNode(nid, ntype, params, BLOCKS[ntype])

        starts = [n for n in self.nodes.values() if n.type == "start"]
        if len(starts) != 1:
            self.err(f"expected exactly one Start block, found {len(starts)}")
        self.start = starts[0] if starts else None
        self._bind_tickers()

        self.data_src: dict[tuple[str, str], tuple[str, str]] = {}
        self.exec_next: dict[tuple[str, str], str] = {}
        for e in flow.get("edges", []):
            self._add_edge(e)

        for n in self.nodes.values():
            self._check_params(n)
        for b, e in options.price_exponents.items():
            if not 0 <= e <= MAX_SCALE:
                self.err(f"price exponent for BUF{b} must be 0..{MAX_SCALE}, got {e}")

        self.reachable = self._reachable_exec()
        self._check_exec_acyclic()
        for nid in self.reachable:
            n = self.nodes[nid]
            for port in n.spec.data_ins:
                if (nid, port) not in self.data_src:
                    self.err(f"{n.type}: input {port!r} is not connected", nid)
        for n in self.nodes.values():
            if n.spec.exec_in and n.id not in self.reachable:
                self.warn(f"{n.type} is not reachable from Start and is not compiled", n.id)

    def _bind_tickers(self) -> None:
        """Get ticker blocks fill BUF0.. in node-id order and stamp those symbols onto Start."""
        tickers = sorted((n for n in self.nodes.values() if n.type == "get_ticker"), key=lambda n: n.id)
        if len(tickers) > NUM_BUFFERS:
            self.err(f"only {NUM_BUFFERS} Get ticker blocks fit in hardware")
        for i, n in enumerate(tickers[:NUM_BUFFERS]):
            n.params["buffer"] = i
            sym = n.params.get("symbol")
            if isinstance(sym, str) and sym.strip() and self.start is not None:
                self.start.params[f"symbol{i}"] = sym.strip().upper()
                n.params["symbol"] = sym.strip().upper()

    def err(self, msg: str, node: str | None = None) -> None:
        self.errors.append(Diagnostic("error", msg, node))

    def warn(self, msg: str, node: str | None = None) -> None:
        self.warnings.append(Diagnostic("warning", msg, node))

    def _add_edge(self, e: dict) -> None:
        src, dst = str(e.get("source")), str(e.get("target"))
        sh, th = str(e.get("sourceHandle") or ""), str(e.get("targetHandle") or "")
        if src not in self.nodes or dst not in self.nodes:
            return
        skind, _, sport = sh.partition(":")
        tkind, _, tport = th.partition(":")
        s, t = self.nodes[src], self.nodes[dst]
        if skind != tkind or skind not in ("exec", "data"):
            self.err(f"edge {src}.{sh} -> {dst}.{th} mixes exec and data ports", dst)
            return
        if skind == "data":
            if sport not in s.spec.data_outs or tport not in t.spec.data_ins:
                self.err(f"edge {src}.{sh} -> {dst}.{th} uses a port that doesn't exist", dst)
            elif (dst, tport) in self.data_src:
                self.err(f"input {tport!r} has more than one connection", dst)
            else:
                self.data_src[(dst, tport)] = (src, sport)
        else:
            if sport not in s.spec.exec_outs or not t.spec.exec_in:
                self.err(f"edge {src}.{sh} -> {dst}.{th} uses a port that doesn't exist", src)
            elif (src, sport) in self.exec_next:
                self.err(f"exec output {sport!r} has more than one connection", src)
            else:
                self.exec_next[(src, sport)] = dst

    def _check_params(self, n: GNode) -> None:
        for key, p in n.spec.params.items():
            v = n.params.get(key)
            if v is None or v == "":
                if p.required:
                    self.err(f"{n.type}: missing parameter {key!r}", n.id)
                continue
            if p.kind in ("int", "number"):
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    self.err(f"{n.type}: {key} must be a number", n.id)
                    continue
                if p.kind == "int" and v != int(v):
                    self.err(f"{n.type}: {key} must be a whole number", n.id)
                    continue
                if (p.lo is not None and v < p.lo) or (p.hi is not None and v > p.hi):
                    self.err(f"{n.type}: {key}={v} out of range [{p.lo}, {p.hi}]", n.id)
                    continue
                n.params[key] = int(v) if p.kind == "int" else v
            elif p.kind == "choice" and v not in p.choices:
                self.err(f"{n.type}: {key}={v!r} must be one of {', '.join(map(str, p.choices))}", n.id)
            elif p.kind == "symbol" and not isinstance(v, str):
                self.err(f"{n.type}: {key} must be a ticker symbol", n.id)
        if n.type == "get_ticker":
            sym = n.params.get("symbol")
            if not isinstance(sym, str) or not sym.strip():
                self.err("get_ticker: missing parameter 'symbol'", n.id)
            elif not re.fullmatch(r"[A-Z][A-Z0-9.]{0,7}", sym.strip().upper()):
                self.err(f"get_ticker: symbol {sym!r} is not a ticker", n.id)
        if n.type == "for" and n.params.get("step") == 0:
            self.err("for: step cannot be 0", n.id)

    def _reachable_exec(self) -> list[str]:
        if not self.start:
            return []
        order, seen, queue = [], set(), [self.start.id]
        while queue:
            nid = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            order.append(nid)
            for port in self.nodes[nid].spec.exec_outs:
                nxt = self.exec_next.get((nid, port))
                if nxt:
                    queue.append(nxt)
        return order

    def _check_exec_acyclic(self) -> None:
        state: dict[str, int] = {}

        def visit(nid: str) -> bool:
            state[nid] = 1
            for port in self.nodes[nid].spec.exec_outs:
                nxt = self.exec_next.get((nid, port))
                if nxt is None:
                    continue
                if state.get(nxt) == 1 or (state.get(nxt) is None and visit(nxt)):
                    return True
            state[nid] = 2
            return False

        if self.start and visit(self.start.id):
            self.err("exec wiring forms a loop; the tick loop is added by the compiler, use For for in-tick loops")


# --------------------------------------------------------------------------- compiler


def _label_base(node_id: str) -> str:
    base = re.sub(r"[^\w.]", "_", node_id)
    return base if base[:1].isalpha() else f"n_{base}"


@dataclass(frozen=True)
class Ctx:
    cont: str  # where a dead end jumps
    key: str  # distinguishes copies of a block emitted in different loop contexts


class Compiler:
    def __init__(self, strategy: Strategy):
        self.g = strategy
        self.pe = strategy.options.price_exponents
        self.items: list[Item] = []
        self.free = list(range(NUM_REGS))
        self.expr_cache: dict[tuple[str, str], Expr] = {}
        self.building: set[tuple[str, str]] = set()
        self.label_names: set[str] = set()
        self.chain_label: dict[tuple[str, str], str] = {}
        self.placed: set[tuple[str, str]] = set()
        self.pending: list = []
        self.used_buffers: set[int] = set()
        self.history = 1
        self.hidden_slots: dict[str, int] = {}
        self.slot_scales: dict[int, int] = {}
        self._cur: str | None = None

    # ---- helpers -----------------------------------------------------------------

    def emit(self, op: Op, comment: str = "", **fields) -> None:
        assert op not in NOT_IN_RTL, op
        self.items.append(Instr(op=op, comment=comment, **fields))

    def place(self, name: str, comment: str = "") -> None:
        self.items.append(Label(name, comment))

    def new_label(self, base: str) -> str:
        name, i = base, 1
        while name in self.label_names:
            i += 1
            name = f"{base}.{i}"
        self.label_names.add(name)
        return name

    def alloc(self) -> int:
        if not self.free:
            raise CompileError(
                [Diagnostic("error", f"expression needs more than {NUM_REGS} registers; split it with Set Variable", self._cur)]
            )
        return self.free.pop(0)

    def release(self, *regs: int) -> None:
        for r in regs:
            assert r not in self.free
            self.free.append(r)
        self.free.sort()

    def load_const(self, r: int, v: int) -> None:
        if not INT32_MIN <= v <= INT32_MAX:
            raise CompileError([Diagnostic("error", f"constant {v} does not fit in 32 bits", self._cur)])
        if IMM16_MIN <= v <= IMM16_MAX:
            self.emit(Op.LOAD_IMM, rd=r, imm=v)
            return
        t = self.alloc()
        self._load_big(r, v, t)
        self.release(t)

    def _load_big(self, r: int, v: int, t: int) -> None:
        if IMM16_MIN <= v <= IMM16_MAX:
            self.emit(Op.LOAD_IMM, rd=r, imm=v)
            return
        q = (abs(v) // IMM16_MAX) * (1 if v > 0 else -1)
        rem = v - q * IMM16_MAX
        self._load_big(r, q, t)
        self.emit(Op.LOAD_IMM, rd=t, imm=IMM16_MAX)
        self.emit(Op.MUL, rd=r, rs1=r, rs2=t)
        if rem:
            self.emit(Op.LOAD_IMM, rd=t, imm=rem)
            self.emit(Op.ADD, rd=r, rs1=r, rs2=t)

    def rescale(self, r: int, frm: int, to: int) -> None:
        if to == frm:
            return
        t = self.alloc()
        self.load_const(t, 10 ** abs(to - frm))
        self.emit(Op.MUL if to > frm else Op.DIV, rd=r, rs1=r, rs2=t)
        self.release(t)

    # ---- data graph -> expressions ------------------------------------------------

    def expr(self, node_id: str, port: str) -> Expr:
        key = (node_id, port)
        if key in self.expr_cache:
            return self.expr_cache[key]
        if key in self.building:
            raise CompileError([Diagnostic("error", "data connections form a cycle", node_id)])
        self.building.add(key)
        e = self._build(self.g.nodes[node_id], port)
        self.building.discard(key)
        self.expr_cache[key] = e
        return e

    def input_expr(self, n: GNode, port: str) -> Expr:
        src = self.g.data_src[(n.id, port)]
        return self.expr(*src)

    def _use_buffer(self, buf: int, history: int) -> None:
        self.used_buffers.add(buf)
        self.history = max(self.history, history)

    def _build(self, n: GNode, port: str) -> Expr:
        p, t = n.params, n.type
        if t in UNSUPPORTED:
            raise CompileError([Diagnostic("error", UNSUPPORTED[t], n.id)])
        if n.spec.history:
            self._use_buffer(int(p["buffer"]), history_ticks(n.spec, p))
        if t in ("current_price", "get_ticker"):
            return Price(p["buffer"], 0)
        if t == "price_n_ticks_ago":
            return Price(p["buffer"], p["n"])
        if t == "sum_n_ticks":
            return Sum(p["buffer"], p["n"])
        if t == "constant":
            c, rounded = to_fixed(float(p["value"]))
            if rounded:
                self.g.warn(f"constant {p['value']} rounded to {MAX_SCALE} decimal places", n.id)
            return c
        if t == "get_var":
            return VarRef(int(str(p["slot"])[3:]) - 1)
        if t == "for":
            return VarRef(self.hidden_slots[n.id])
        if t in ("add", "subtract", "multiply", "divide"):
            op = {"add": "add", "subtract": "sub", "multiply": "mul", "divide": "div"}[t]
            return Bin(op, self.input_expr(n, "a"), self.input_expr(n, "b"))
        if t == "power":
            base, e = self.input_expr(n, "base"), p["exponent"]
            if e == 0:
                return Const(1, 0)
            out = base
            for _ in range(e - 1):
                out = Bin("mul", out, base)
            return out
        if t == "sqrt":
            return Sqrt(self.input_expr(n, "x"))
        if t == "sma":
            return Bin("div", Sum(p["buffer"], p["n"]), Const(p["n"], 0))
        if t == "momentum":
            return Bin("sub", Bin("div", Price(p["buffer"], 0), Price(p["buffer"], p["n"])), Const(1, 0))
        if t == "volatility":
            return Volatility(p["buffer"], p["n"])
        if t == "mean_reversion_bands":
            sma = Bin("div", Sum(p["buffer"], p["n"]), Const(p["n"], 0))
            if port == "middle":
                return sma
            k, _ = to_fixed(float(p["k"]))
            band = Bin("mul", k, Volatility(p["buffer"], p["n"]))
            return Bin("add" if port == "upper" else "sub", sma, band)
        raise CompileError([Diagnostic("error", f"{t} has no data output", n.id)])

    def scale(self, e: Expr) -> int:
        if isinstance(e, Const):
            return e.scale
        if isinstance(e, (Price, Sum, Volatility)):
            return self.pe[e.buf]
        if isinstance(e, VarRef):
            return self.slot_scales.get(e.slot, 0)
        if isinstance(e, Sqrt):
            return _even_at_least_4(self.scale(e.x)) // 2
        sa, sb = self.scale(e.a), self.scale(e.b)
        if e.op in ("add", "sub"):
            return max(sa, sb)
        if e.op == "mul":
            return min(sa + sb, MAX_SCALE)
        return div_scales(sa, sb)[0]

    def need(self, e: Expr) -> int:
        if isinstance(e, Const):
            return 1 if IMM16_MIN <= e.value <= IMM16_MAX else 2
        if isinstance(e, (Price, Sum, VarRef)):
            return 1
        if isinstance(e, Sqrt):
            return max(self.need(e.x), 4)
        if isinstance(e, Volatility):
            return 4
        na, nb = self.need(e.a), self.need(e.b)
        return max(na, nb, min(na, nb) + 1) + 1

    # ---- expression codegen -------------------------------------------------------

    def ev_at(self, e: Expr, scale: int) -> int:
        """Evaluate at a given (higher or equal) scale; constants are rescaled at compile time."""
        if isinstance(e, Const) and scale >= e.scale:
            r = self.alloc()
            self.load_const(r, e.value * 10 ** (scale - e.scale))
            return r
        r, s = self.ev(e)
        self.rescale(r, s, scale)
        return r

    def ev_pair(self, a: Expr, b: Expr) -> tuple[int, int, int]:
        """Evaluate two operands at their common scale, larger register need first."""
        s = max(self.scale(a), self.scale(b))
        if self.need(b) > self.need(a):
            rb = self.ev_at(b, s)
            ra = self.ev_at(a, s)
        else:
            ra = self.ev_at(a, s)
            rb = self.ev_at(b, s)
        return ra, rb, s

    def ev(self, e: Expr) -> tuple[int, int]:
        """Evaluate into a fresh register. Returns (register, scale)."""
        if isinstance(e, Const):
            r = self.alloc()
            self.load_const(r, e.value)
            return r, e.scale
        if isinstance(e, Price):
            r = self.alloc()
            if e.offset == 0:
                self.emit(Op.GETSTOCKPRICE, rd=r, buf=e.buf)
            else:
                self.emit(Op.GETSTOCKPRICEBEFORE, rd=r, buf=e.buf, imm5=e.offset)
            return r, self.pe[e.buf]
        if isinstance(e, Sum):
            r = self.alloc()
            self.emit(Op.GETSUMPRICEBEFORE, rd=r, buf=e.buf, imm5=e.n)
            return r, self.pe[e.buf]
        if isinstance(e, VarRef):
            r = self.alloc()
            self.emit(Op.GETVAR, rd=r, var=e.slot)
            return r, self.slot_scales.get(e.slot, 0)
        if isinstance(e, Sqrt):
            rv, s = self.ev(e.x)
            target = _even_at_least_4(s)
            self.rescale(rv, s, target)
            rx = self.isqrt(rv)
            self.release(rv)
            return rx, target // 2
        if isinstance(e, Volatility):
            return self.volatility(e)

        if e.op in ("add", "sub"):
            ra, rb, s = self.ev_pair(e.a, e.b)
            self.emit(Op.ADD if e.op == "add" else Op.SUB, rd=ra, rs1=ra, rs2=rb)
            self.release(rb)
            return ra, s

        if self.need(e.b) > self.need(e.a):
            rb, sb = self.ev(e.b)
            ra, sa = self.ev(e.a)
        else:
            ra, sa = self.ev(e.a)
            rb, sb = self.ev(e.b)
        if e.op == "mul":
            self.emit(Op.MUL, rd=ra, rs1=ra, rs2=rb)
            s = sa + sb
            if s > MAX_SCALE:
                self.rescale(ra, s, MAX_SCALE)
                s = MAX_SCALE
        else:
            s, k = div_scales(sa, sb)
            if k > 0:
                self.rescale(ra, sa, sa + k)
            self.emit(Op.DIV, rd=ra, rs1=ra, rs2=rb)
            if k < 0:
                self.rescale(ra, -k, 0)
        self.release(rb)
        return ra, s

    def isqrt(self, v: int) -> int:
        """Integer square root of register v (Newton, monotone from x=v). Result in a new register."""
        x, y, t = self.alloc(), self.alloc(), self.alloc()
        loop, body, done = self.new_label("sqrt_loop"), self.new_label("sqrt_step"), self.new_label("sqrt_done")
        self.emit(Op.LOAD_IMM, rd=t, imm=0, comment="isqrt: x = v")
        self.emit(Op.ADD, rd=x, rs1=v, rs2=t)
        self.emit(Op.LOAD_IMM, rd=t, imm=2)
        self.emit(Op.CMP_LT, rd=t, rs1=v, rs2=t)
        self.emit(Op.JMP_IF, rs1=t, target=done, comment="v < 2: sqrt(v) = v")
        self.emit(Op.LOAD_IMM, rd=t, imm=1)
        self.emit(Op.ADD, rd=y, rs1=x, rs2=t)
        self.emit(Op.LOAD_IMM, rd=t, imm=2)
        self.emit(Op.DIV, rd=y, rs1=y, rs2=t, comment="y = (x + 1) / 2")
        self.place(loop)
        self.emit(Op.CMP_LT, rd=t, rs1=y, rs2=x)
        self.emit(Op.JMP_IF, rs1=t, target=body, comment="while y < x")
        self.emit(Op.JMP, target=done)
        self.place(body)
        self.emit(Op.LOAD_IMM, rd=t, imm=0)
        self.emit(Op.ADD, rd=x, rs1=y, rs2=t, comment="x = y")
        self.emit(Op.DIV, rd=y, rs1=v, rs2=x)
        self.emit(Op.ADD, rd=y, rs1=y, rs2=x)
        self.emit(Op.LOAD_IMM, rd=t, imm=2)
        self.emit(Op.DIV, rd=y, rs1=y, rs2=t, comment="y = (x + v / x) / 2")
        self.emit(Op.JMP, target=loop)
        self.place(done)
        self.release(y, t)
        return x

    def volatility(self, e: Volatility) -> tuple[int, int]:
        """Sample std dev over the last n ticks, unrolled (imm5 offsets are immediates)."""
        pe = self.pe[e.buf]
        m, t, acc = self.alloc(), self.alloc(), self.alloc()
        self.emit(Op.GETSUMPRICEBEFORE, rd=m, buf=e.buf, imm5=e.n, comment=f"volatility(BUF{e.buf}, {e.n})")
        self.emit(Op.LOAD_IMM, rd=t, imm=e.n)
        self.emit(Op.DIV, rd=m, rs1=m, rs2=t, comment="mean")
        self.emit(Op.LOAD_IMM, rd=acc, imm=0)
        for i in range(e.n):
            if i == 0:
                self.emit(Op.GETSTOCKPRICE, rd=t, buf=e.buf)
            else:
                self.emit(Op.GETSTOCKPRICEBEFORE, rd=t, buf=e.buf, imm5=i)
            self.emit(Op.SUB, rd=t, rs1=t, rs2=m)
            self.emit(Op.MUL, rd=t, rs1=t, rs2=t)
            self.emit(Op.ADD, rd=acc, rs1=acc, rs2=t)
        self.emit(Op.LOAD_IMM, rd=t, imm=e.n - 1)
        self.emit(Op.DIV, rd=acc, rs1=acc, rs2=t, comment="variance")
        self.release(m, t)
        target = _even_at_least_4(2 * pe)
        self.rescale(acc, 2 * pe, target)
        x = self.isqrt(acc)
        self.release(acc)
        return x, target // 2

    # ---- exec codegen -------------------------------------------------------------

    def branch_label(self, target: str | None, ctx: Ctx) -> str:
        if target is None:
            return ctx.cont
        key = (target, ctx.key)
        if key not in self.chain_label:
            base = _label_base(target) if ctx.key == "main" else f"{_label_base(target)}.in"
            self.chain_label[key] = self.new_label(base)
            self.pending.append(("chain", target, ctx))
        return self.chain_label[key]

    def gen_chain(self, node_id: str | None, ctx: Ctx) -> None:
        while True:
            if node_id is None:
                self.emit(Op.JMP, target=ctx.cont)
                return
            key = (node_id, ctx.key)
            if key in self.placed:
                self.emit(Op.JMP, target=self.chain_label[key])
                return
            if key not in self.chain_label:
                base = _label_base(node_id) if ctx.key == "main" else f"{_label_base(node_id)}.in"
                self.chain_label[key] = self.new_label(base)
            self.placed.add(key)
            n = self.g.nodes[node_id]
            self.place(self.chain_label[key], self.describe(n))
            self._cur = node_id
            node_id = getattr(self, f"gen_{n.type}")(n, ctx)
            assert len(self.free) == NUM_REGS, f"register leak in {n.type}"

    def describe(self, n: GNode) -> str:
        p = n.params
        if n.type == "if":
            return f"If A {p['operator']} B"
        if n.type in ("buy", "sell"):
            return f"{n.type.capitalize()} {p['quantity']} x BUF{p['buffer']}"
        if n.type == "set_var":
            return f"Set {p['slot']}"
        if n.type == "for":
            return f"For i in range({p['start']}, {p['end']}, {p['step']})"
        return n.type

    def gen_set_var(self, n: GNode, ctx: Ctx) -> str | None:
        slot = int(str(n.params["slot"])[3:]) - 1
        r, s = self.ev(self.input_expr(n, "value"))
        self.rescale(r, s, self.slot_scales[slot])
        self.emit(Op.ASSIGNVAR, var=slot, rs1=r, comment=f"scale 10^{self.slot_scales[slot]}")
        self.release(r)
        return self.g.exec_next.get((n.id, "out"))

    def gen_if(self, n: GNode, ctx: Ctx) -> str | None:
        ra, rb, _ = self.ev_pair(self.input_expr(n, "a"), self.input_expr(n, "b"))
        # (opcode, branch taken when the result is nonzero). No NOT/CMP_GTE in the RTL,
        # so >=, <= and == test the opposite condition and jump to Else instead.
        op, jump_to = {
            ">": (Op.CMP_GT, "then"),
            "<": (Op.CMP_LT, "then"),
            ">=": (Op.CMP_LT, "else"),
            "<=": (Op.CMP_GT, "else"),
            "==": (Op.SUB, "else"),
            "!=": (Op.SUB, "then"),
        }[n.params["operator"]]
        self.emit(op, rd=ra, rs1=ra, rs2=rb)
        self.release(rb)
        target = self.branch_label(self.g.exec_next.get((n.id, jump_to)), ctx)
        self.emit(Op.JMP_IF, rs1=ra, target=target)
        self.release(ra)
        return self.g.exec_next.get((n.id, "else" if jump_to == "then" else "then"))

    def gen_for(self, n: GNode, ctx: Ctx) -> str | None:
        slot = self.hidden_slots[n.id]
        start, end, step = n.params["start"], n.params["end"], n.params["step"]
        base = _label_base(n.id)
        head, step_lbl = self.new_label(f"{base}.head"), self.new_label(f"{base}.step")
        r = self.alloc()
        self.load_const(r, start)
        self.emit(Op.ASSIGNVAR, var=slot, rs1=r, comment="loop counter")
        self.release(r)
        self.place(head)
        r, t = self.alloc(), self.alloc()
        self.emit(Op.GETVAR, rd=r, var=slot)
        self.load_const(t, end)
        self.emit(Op.CMP_LT if step > 0 else Op.CMP_GT, rd=r, rs1=r, rs2=t)
        self.release(t)
        body_ctx = Ctx(cont=step_lbl, key=f"{ctx.key}/{n.id}")
        body = self.branch_label(self.g.exec_next.get((n.id, "body")), body_ctx)
        self.emit(Op.JMP_IF, rs1=r, target=body)
        self.release(r)

        def emit_step() -> None:
            self.place(step_lbl)
            r, t = self.alloc(), self.alloc()
            self.emit(Op.GETVAR, rd=r, var=slot)
            self.load_const(t, step)
            self.emit(Op.ADD, rd=r, rs1=r, rs2=t)
            self.emit(Op.ASSIGNVAR, var=slot, rs1=r)
            self.release(r, t)
            self.emit(Op.JMP, target=head)

        self.pending.append(("raw", emit_step))
        return self.g.exec_next.get((n.id, "after"))

    def _trade(self, n: GNode, sell: bool) -> str | None:
        buf, qty = n.params["buffer"], n.params["quantity"]
        self._use_buffer(buf, 1)
        rp, rq = self.alloc(), self.alloc()
        self.emit(Op.GETSTOCKPRICE, rd=rp, buf=buf)
        self.load_const(rq, qty)
        self.emit(Op.MUL, rd=rp, rs1=rp, rs2=rq, comment="cost = price x qty")
        self.rescale(rp, self.pe[buf], BALANCE_EXP)
        if sell:
            t = self.alloc()
            self.emit(Op.LOAD_IMM, rd=t, imm=0)
            self.emit(Op.SUB, rd=rp, rs1=t, rs2=rp, comment="negative amount = sell, cash up")
            self.release(t)
        self.emit(Op.UPDATEBALANCE, rs1=rp, buf=buf, comment="BALANCE -= amount")
        self.emit(Op.EMITDECISION, rs1=rq, buf=buf, imm5=0 if sell else 1)
        self.release(rp, rq)
        return self.g.exec_next.get((n.id, "out"))

    def gen_buy(self, n: GNode, ctx: Ctx) -> str | None:
        return self._trade(n, sell=False)

    def gen_sell(self, n: GNode, ctx: Ctx) -> str | None:
        return self._trade(n, sell=True)

    # ---- driver -------------------------------------------------------------------

    def prepare(self) -> None:
        g = self.g
        self._cur = None
        user_slots = {
            int(str(n.params["slot"])[3:]) - 1
            for n in g.nodes.values()
            if n.type in ("set_var", "get_var") and str(n.params.get("slot", "")).startswith("VAR")
        }
        spare = [s for s in reversed(range(NUM_VARS)) if s not in user_slots]
        for nid in g.reachable:
            if g.nodes[nid].type == "for":
                if not spare:
                    g.err(f"no free variable slot for the loop counter ({NUM_VARS} slots, all used)", nid)
                    return
                self.hidden_slots[nid] = spare.pop(0)

        exec_inputs = []
        for nid in g.reachable:
            n = g.nodes[nid]
            for port in n.spec.data_ins:
                if (nid, port) in g.data_src:
                    self._cur = nid
                    exec_inputs.append((n, self.input_expr(n, port)))
            if n.type in ("buy", "sell"):
                self._use_buffer(n.params["buffer"], 1)

        self.slot_scales = {s: 0 for s in range(NUM_VARS)}
        sets = [(n, e) for n, e in exec_inputs if n.type == "set_var"]
        for _ in range(4 * (MAX_SCALE + 1)):
            changed = False
            for n, e in sets:
                slot = int(str(n.params["slot"])[3:]) - 1
                s = self.scale(e)
                if s > self.slot_scales[slot]:
                    self.slot_scales[slot] = s
                    changed = True
            if not changed:
                break

        set_slots = {int(str(n.params["slot"])[3:]) - 1 for n, _ in sets}
        for n in g.nodes.values():
            if n.type == "get_var":
                slot = int(str(n.params["slot"])[3:]) - 1
                if slot not in set_slots:
                    g.warn(f"{n.params['slot']} is read but never set by a reachable block (reads 0)", n.id)

        start = g.start.params if g.start else {}
        for b in sorted(self.used_buffers):
            if not start.get(f"symbol{b}"):
                g.err(f"BUF{b} is used but no Get ticker block supplies it", g.start.id if g.start else None)

    def compile(self) -> list[Item]:
        g = self.g
        start = g.start
        assert start is not None
        cents = round(float(start.params["startingBalance"]) * 10**BALANCE_EXP)
        warmup = self.history - 1

        self.place("START", f"{g.name} | resolution {start.params['resolution']}")
        r = self.alloc()
        self._cur = start.id
        self.load_const(r, cents)
        self.emit(Op.SETBALANCE, rs1=r, comment=f"starting cash ${start.params['startingBalance']:,}")
        self.emit(Op.GETBALANCE, rd=r)
        self.emit(Op.EMITBALANCE, rs1=r, comment="load handshake")
        self.release(r)
        if warmup > 0:
            n, one, bal = self.alloc(), self.alloc(), self.alloc()
            self.emit(Op.LOAD_IMM, rd=n, imm=warmup, comment=f"warm-up: fill {self.history} ticks of history")
            self.emit(Op.LOAD_IMM, rd=one, imm=1)
            self.place(self.new_label("WARMUP"))
            self.emit(Op.UPDATEALLSTOCKBUFFERS)
            self.emit(Op.GETBALANCE, rd=bal)
            self.emit(Op.EMITBALANCE, rs1=bal, comment="tick ack")
            self.emit(Op.SUB, rd=n, rs1=n, rs2=one)
            self.emit(Op.JMP_IF, rs1=n, target="WARMUP")
            self.release(n, one, bal)
        self.label_names.update({"START", "TICK", "TICK_END"})

        self.place("TICK", "one pass per tick round")
        self.emit(Op.UPDATEALLSTOCKBUFFERS, comment="wait for a tick on all 5 buffers")
        self.gen_chain(g.exec_next.get((start.id, "out")), Ctx("TICK_END", "main"))
        while self.pending:
            item = self.pending.pop(0)
            if item[0] == "raw":
                item[1]()
            else:
                _, target, ctx = item
                if (target, ctx.key) not in self.placed:
                    self.gen_chain(target, ctx)

        self.place("TICK_END")
        r = self.alloc()
        self.emit(Op.GETBALANCE, rd=r)
        self.emit(Op.EMITBALANCE, rs1=r, comment="tick ack")
        self.emit(Op.JMP, target="TICK")
        self.release(r)
        return peephole(self.items)


def compile_strategy(doc: dict, options: CompileOptions | None = None) -> CompileResult:
    options = options or CompileOptions()
    g = Strategy(doc, options)
    if g.errors:
        raise CompileError(g.errors + g.warnings)
    c = Compiler(g)
    c.prepare()
    if g.errors:
        raise CompileError(g.errors + g.warnings)
    items = c.compile()
    try:
        assembled = assemble(items)
    except ValueError as e:
        raise CompileError([Diagnostic("error", str(e))]) from None

    start = g.start.params  # type: ignore[union-attr]
    manifest = {
        "schema": COMPILED_SCHEMA,
        "name": g.name,
        "isa": "tradecpu",
        "resolution": start["resolution"],
        "barMinutes": RESOLUTIONS[start["resolution"]],
        "startingBalance": start["startingBalance"],
        "balanceExponent": BALANCE_EXP,
        "historyTicks": c.history,
        "warmupTicks": c.history - 1,
        "buffers": [
            {
                "buf": b,
                "symbol": start.get(f"symbol{b}") or None,
                "priceExponent": options.price_exponents.get(b, 2),
                "used": b in c.used_buffers,
            }
            for b in range(NUM_BUFFERS)
        ],
        "variableSlots": {
            "user": sorted(f"VAR{s + 1}" for s in {int(str(n.params['slot'])[3:]) - 1 for n in g.nodes.values() if n.type in ('set_var', 'get_var')}),
            "loopCounters": {nid: f"VAR{s + 1}" for nid, s in c.hidden_slots.items()},
            "scales": {f"VAR{s + 1}": sc for s, sc in c.slot_scales.items() if sc},
        },
        "programWords": len(assembled.words),
        "words": [f"0x{w:08X}" for w in assembled.words],
        "protocol": {
            "onLoad": "one EMIT_BALANCE (starting cash)",
            "perTick": "send one TICK per buffer (all 5), then read DECISION_EVENTs until one EMIT_BALANCE",
        },
        "warnings": [w.to_json() for w in g.warnings],
    }
    return CompileResult(items=items, assembled=assembled, manifest=manifest, warnings=g.warnings)
