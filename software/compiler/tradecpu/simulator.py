"""Golden model of the TradeCPU, matching hardware/rtl behaviour instruction for instruction.

Cycle counts follow control_unit.v's FSM (FETCH, DECODE, [FETCH2], EXECUTE, WRITEBACK):
4 cycles for a 1-word op, 5 for a 2-word op, 20 for DIV, N+3 for GETSUMPRICEBEFORE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .isa import BUFFER_DEPTH, NOT_IN_RTL, NUM_BUFFERS, NUM_VARS, PROGRAM_WORDS, Op, decode


def to_i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def to_i16(v: int) -> int:
    v &= 0xFFFF
    return v - (1 << 16) if v & 0x8000 else v


def div_trunc(a: int, b: int) -> int:
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return to_i32(-q if (a < 0) != (b < 0) else q)


@dataclass(frozen=True)
class Decision:
    buf: int
    action: str  # "buy" | "sell"
    quantity: int


@dataclass(frozen=True)
class BalanceMsg:
    value: int


Message = Decision | BalanceMsg


class SimError(RuntimeError):
    pass


@dataclass
class TradeCPU:
    words: list[int]
    strict: bool = True
    regs: list[int] = field(default_factory=lambda: [0] * 8)
    vars: list[int] = field(default_factory=lambda: [0] * NUM_VARS)
    balance: int = 0
    pc: int = 0
    cycles: int = 0
    outbox: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.words) > PROGRAM_WORDS:
            raise SimError(f"program too large: {len(self.words)} words")
        self.mem = list(self.words) + [0] * (PROGRAM_WORDS - len(self.words))
        self.bufs = [[0] * BUFFER_DEPTH for _ in range(NUM_BUFFERS)]
        self.heads = [0] * NUM_BUFFERS
        self.staged: list[int | None] = [None] * NUM_BUFFERS

    def tick(self, buf: int, price: int) -> None:
        if 0 <= buf < NUM_BUFFERS:
            self.staged[buf] = to_i16(price)

    def _buf_read(self, b: int, days: int) -> int:
        if not 0 <= b < NUM_BUFFERS:
            return 0
        days = days - BUFFER_DEPTH if days >= BUFFER_DEPTH else days
        return self.bufs[b][(self.heads[b] - days) % BUFFER_DEPTH]

    def step(self) -> bool:
        """Execute one instruction. Returns False if blocked on UPDATEALLSTOCKBUFFERS."""
        ins = decode(self.mem, self.pc)
        op = ins.op
        if self.strict and op in NOT_IN_RTL:
            raise SimError(f"pc={self.pc}: {op.name} is not implemented in the RTL")
        r = self.regs
        a, b = r[ins.rs1], r[ins.rs2]
        next_pc = self.pc + (2 if op in (Op.LOAD_IMM, Op.JMP, Op.JMP_IF) else 1)
        cycles = 5 if op in (Op.LOAD_IMM, Op.JMP, Op.JMP_IF) else 4

        if op == Op.ADD:
            r[ins.rd] = to_i32(a + b)
        elif op == Op.SUB:
            r[ins.rd] = to_i32(a - b)
        elif op == Op.MUL:
            r[ins.rd] = to_i32(a * b)
        elif op == Op.DIV:
            r[ins.rd] = div_trunc(a, b)
            cycles = 20
        elif op == Op.CMP_GT:
            r[ins.rd] = int(a > b)
        elif op == Op.CMP_LT:
            r[ins.rd] = int(a < b)
        elif op == Op.CMP_GTE:
            r[ins.rd] = int(a >= b)
        elif op == Op.CMP_LTE:
            r[ins.rd] = int(a <= b)
        elif op == Op.AND:
            r[ins.rd] = int(bool(a) and bool(b))
        elif op == Op.OR:
            r[ins.rd] = int(bool(a) or bool(b))
        elif op == Op.SELECT:
            r[ins.rd] = b if a != 0 else r[ins.rs3]
        elif op == Op.LOAD_IMM:
            r[ins.rd] = ins.imm
        elif op == Op.JMP:
            next_pc = int(ins.target)  # type: ignore[arg-type]
        elif op == Op.JMP_IF:
            if a != 0:
                next_pc = int(ins.target)  # type: ignore[arg-type]
        elif op == Op.ASSIGNVAR:
            if ins.var < NUM_VARS:
                self.vars[ins.var] = to_i16(a)
        elif op == Op.GETVAR:
            r[ins.rd] = self.vars[ins.var] if ins.var < NUM_VARS else 0
        elif op == Op.GETBALANCE:
            r[ins.rd] = self.balance
        elif op == Op.GETSTOCKPRICE:
            r[ins.rd] = self._buf_read(ins.buf, 0)
        elif op == Op.GETSTOCKPRICEBEFORE:
            r[ins.rd] = self._buf_read(ins.buf, ins.imm5)
        elif op == Op.GETSUMPRICEBEFORE:
            n = min(ins.imm5, BUFFER_DEPTH)
            r[ins.rd] = to_i32(sum(self._buf_read(ins.buf, d) for d in range(n)))
            cycles = n + 3 if n else 4
        elif op == Op.UPDATEBALANCE:
            self.balance = to_i32(self.balance - a)
        elif op == Op.SETBALANCE:
            self.balance = a
        elif op == Op.UPDATEALLSTOCKBUFFERS:
            if any(s is None for s in self.staged):
                return False
            for i in range(NUM_BUFFERS):
                self.heads[i] = (self.heads[i] + 1) % BUFFER_DEPTH
                self.bufs[i][self.heads[i]] = self.staged[i]  # type: ignore[assignment]
                self.staged[i] = None
        elif op == Op.EMITDECISION:
            self.outbox.append(Decision(ins.buf, "buy" if ins.imm5 else "sell", to_i16(a)))
        elif op == Op.EMITBALANCE:
            self.outbox.append(BalanceMsg(a))
        elif op in (Op.NOP, Op.HALT):
            pass

        self.pc = next_pc
        self.cycles += cycles
        return True

    def run_until_blocked(self, max_steps: int = 1_000_000) -> None:
        for _ in range(max_steps):
            if not self.step():
                return
        raise SimError(f"no UPDATEALLSTOCKBUFFERS within {max_steps} instructions (runaway loop?)")

    def drain(self) -> list[Message]:
        out, self.outbox = self.outbox, []
        return out


def run_rounds(words: list[int], rounds: list[list[int]], strict: bool = True):
    """Load a program, then feed one round of 5 ticks at a time.

    Returns (messages at load, [messages per round], [cycles per round]).
    """
    cpu = TradeCPU(words, strict=strict)
    cpu.run_until_blocked()
    at_load = cpu.drain()
    per_round: list[list[Message]] = []
    cycles: list[int] = []
    for prices in rounds:
        if len(prices) != NUM_BUFFERS:
            raise ValueError(f"each round needs {NUM_BUFFERS} prices")
        for b, p in enumerate(prices):
            cpu.tick(b, p)
        start = cpu.cycles
        cpu.run_until_blocked()
        per_round.append(cpu.drain())
        cycles.append(cpu.cycles - start)
    return at_load, per_round, cycles
