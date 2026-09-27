"""Run a compiled strategy on the FPGA over UART with synthetic prices and check every message
against the golden-model simulator.

The UART framing matches hardware/python/balance_test.py. With `dry_run`, a FakeBoard backed by
the simulator stands in for the serial port, so the whole path (framing, parsing, comparison)
can be exercised without hardware.
"""

from __future__ import annotations

import csv
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .isa import IMM16_MAX, NUM_BUFFERS, load_program_message, tick_message
from .simulator import BalanceMsg, Decision, Message, TradeCPU, run_rounds

MSG_DECISION = 0x03
MSG_BALANCE = 0x04

# Distinct base prices (in dollars) so multi-stock strategies see different series per buffer.
BASE_DOLLARS = (150.0, 90.0, 210.0, 45.0, 120.0)

PATTERNS = ("sine", "walk", "ramp", "steps", "spikes", "flat")


# ---------------------------------------------------------------- dummy data

def _series(pattern: str, n: int, base: float, phase: int, rng: random.Random) -> list[float]:
    """One buffer's prices in dollars."""
    if pattern == "flat":
        return [base] * n
    if pattern == "sine":
        # Period of 24 ticks crosses short and long moving averages regularly.
        return [base * (1 + 0.05 * math.sin(2 * math.pi * (i + phase) / 24)) for i in range(n)]
    if pattern == "ramp":
        half = max(n // 2, 1)
        return [base * (1 + 0.15 * (i if i < half else 2 * half - i) / half) for i in range(n)]
    if pattern == "steps":
        return [base * (1.08 if (i // 10 + phase) % 2 else 0.94) for i in range(n)]
    if pattern == "spikes":
        return [base * (1.12 if i % 17 == 16 else 0.88 if i % 23 == 22 else 1.0) for i in range(n)]
    if pattern == "walk":
        p, out = base, []
        for _ in range(n):
            p *= 1 + rng.gauss(0, 0.01)
            out.append(p)
        return out
    raise ValueError(f"unknown pattern {pattern!r}; choose from {', '.join(PATTERNS)} or a CSV path")


def make_rounds(pattern: str, n: int, price_exps: dict[int, int], seed: int = 0) -> list[list[int]]:
    """n rounds of 5 scaled int16 prices (price = dollars x 10^exp)."""
    rng = random.Random(seed)
    cols = []
    for b in range(NUM_BUFFERS):
        scale = 10 ** price_exps.get(b, 2)
        dollars = _series(pattern, n, BASE_DOLLARS[b], phase=5 * b, rng=rng)
        cols.append([max(1, min(IMM16_MAX, round(d * scale))) for d in dollars])
    return [list(r) for r in zip(*cols)]


def read_csv_rounds(path: str | Path) -> list[list[int]]:
    """CSV with columns buf0..buf4 of already-scaled integer prices; missing columns repeat 100."""
    with open(path) as f:
        return [[int(row.get(f"buf{b}") or 100) for b in range(NUM_BUFFERS)] for row in csv.DictReader(f)]


# ---------------------------------------------------------------- UART

class Port(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read(self, n: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


def encode_message(m: Message) -> bytes:
    if isinstance(m, Decision):
        return bytes([MSG_DECISION, m.buf, 1 if m.action == "buy" else 0]) + m.quantity.to_bytes(
            2, "little", signed=True
        )
    return bytes([MSG_BALANCE]) + m.value.to_bytes(4, "little", signed=True)


def read_message(port: Port) -> Message | tuple | None:
    """One board->host message (same parsing as balance_test.py). None on timeout."""
    head = port.read(1)
    if not head:
        return None
    body = port.read(4)
    if len(body) != 4:
        return ("TRUNCATED", head[0], body)
    if head[0] == MSG_DECISION:
        return Decision(body[0], "buy" if body[1] else "sell", int.from_bytes(body[2:4], "little", signed=True))
    if head[0] == MSG_BALANCE:
        return BalanceMsg(int.from_bytes(body, "little", signed=True))
    return ("UNKNOWN", head[0], body)


@dataclass
class FakeBoard:
    """Serial-port stand-in that parses host frames and answers from the simulator.

    Like the real board, stock buffer contents survive LOAD_PROGRAM, so this also checks that
    the compiler's warm-up flushes stale history.
    """

    cpu: TradeCPU | None = None
    rx: bytearray = field(default_factory=bytearray)
    tx: bytearray = field(default_factory=bytearray)

    def write(self, data: bytes) -> int:
        self.rx += data
        while self._consume():
            pass
        return len(data)

    def _consume(self) -> bool:
        if not self.rx:
            return False
        kind = self.rx[0]
        if kind == 0x01:
            if len(self.rx) < 3:
                return False
            size = int.from_bytes(self.rx[1:3], "little")
            if len(self.rx) < 3 + size:
                return False
            body, self.rx = bytes(self.rx[3 : 3 + size]), self.rx[3 + size :]
            words = [int.from_bytes(body[i : i + 4], "little") for i in range(0, size, 4)]
            old = self.cpu
            self.cpu = TradeCPU(words)
            if old is not None:
                self.cpu.bufs, self.cpu.heads = old.bufs, old.heads
        elif kind == 0x02:
            if len(self.rx) < 4:
                return False
            buf, price = self.rx[1], int.from_bytes(self.rx[2:4], "little", signed=True)
            self.rx = self.rx[4:]
            if self.cpu:
                self.cpu.tick(buf, price)
        else:
            self.rx = self.rx[1:]
            return True
        if self.cpu:
            self.cpu.run_until_blocked()
            for m in self.cpu.drain():
                self.tx += encode_message(m)
        return True

    def read(self, n: int) -> bytes:
        out, self.tx = bytes(self.tx[:n]), self.tx[n:]
        return out

    @property
    def in_waiting(self) -> int:
        return len(self.tx)

    def reset_input_buffer(self) -> None:
        self.tx.clear()

    def close(self) -> None:
        pass


def open_serial(port: str, baud: int) -> Port:
    try:
        import serial  # pyserial
    except ImportError as e:
        raise SystemExit("pyserial is required for hardware runs: pip install pyserial") from e
    ser = serial.Serial(port, baudrate=baud, timeout=2)
    time.sleep(0.5)
    ser.reset_input_buffer()
    return ser


# ---------------------------------------------------------------- run + compare

def fmt(m) -> str:
    if m is None:
        return "(nothing -- timed out)"
    if isinstance(m, Decision):
        return f"DECISION buf{m.buf} {m.action.upper():4s} qty={m.quantity}"
    if isinstance(m, BalanceMsg):
        return f"BALANCE {m.value:>11} (${m.value / 100:,.2f})"
    return repr(m)


def read_until_balance(port: Port, limit: int = 64) -> list:
    """Read messages until an EMIT_BALANCE (the per-round ack) or a timeout."""
    got: list = []
    for _ in range(limit):
        m = read_message(port)
        got.append(m)
        if m is None or isinstance(m, BalanceMsg):
            break
    return got


@dataclass
class RunReport:
    pattern: str
    rounds: int
    warmup: int
    failures: int = 0
    buys: int = 0
    sells: int = 0
    holds: int = 0
    final_balance: int | None = None
    load_s: float = 0.0
    rounds_s: float = 0.0
    lines: list[str] = field(default_factory=list)


def run_pattern(
    port: Port,
    words: list[int],
    rounds: list[list[int]],
    pattern: str,
    warmup: int,
    tick_delay: float = 0.0,
    verbose: bool = False,
) -> RunReport:
    at_load, expected, _ = run_rounds(words, rounds)
    rep = RunReport(pattern, len(rounds), warmup)

    def check(tag: str, exp: list, got: list) -> None:
        ok = exp == got
        rep.failures += not ok
        if ok and not verbose:
            return
        rep.lines.append(f"  [{tag}] {'PASS' if ok else 'FAIL'}")
        for i in range(max(len(exp), len(got))):
            e = exp[i] if i < len(exp) else "(none)"
            g = got[i] if i < len(got) else "(none)"
            mark = "" if e == g else "   <-- mismatch"
            rep.lines.append(f"     expected {fmt(e) if e != '(none)' else e:40s} got {fmt(g) if g != '(none)' else g}{mark}")

    t0 = time.perf_counter()
    port.write(load_program_message(words))
    loaded = read_until_balance(port)
    rep.load_s = time.perf_counter() - t0
    check("load", at_load, loaded)

    t0 = time.perf_counter()
    for i, (prices, exp) in enumerate(zip(rounds, expected)):
        for b, p in enumerate(prices):
            port.write(tick_message(b, p))
            if tick_delay:
                time.sleep(tick_delay)
        got = read_until_balance(port)
        tag = f"{'warm-up' if i < warmup else 'round'} {i:3d} prices={prices}"
        check(tag, exp, got)
        if got and got[-1] is None:
            rep.lines.append("  board stopped responding; aborting this pattern")
            break
        decisions = [m for m in exp if isinstance(m, Decision)]
        if i >= warmup:
            rep.buys += sum(m.action == "buy" for m in decisions)
            rep.sells += sum(m.action == "sell" for m in decisions)
            rep.holds += not decisions
        if exp and isinstance(exp[-1], BalanceMsg):
            rep.final_balance = exp[-1].value
    rep.rounds_s = time.perf_counter() - t0

    extra = port.read(getattr(port, "in_waiting", 0) or 0)
    if extra:
        rep.failures += 1
        rep.lines.append(f"  FAIL: unexpected extra bytes after last round: {extra.hex(' ')}")
    return rep
