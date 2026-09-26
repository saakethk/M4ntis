"""TradeCPU instruction set: opcodes, operand signatures and word encoding.

Source of truth: hardware/docs/tradecpu_full_specification.md (sections 1, 3, 4)
cross-checked against hardware/rtl/control_unit.v and alu.v.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

NUM_REGS = 8
NUM_VARS = 15
NUM_BUFFERS = 5
BUFFER_DEPTH = 30
PROGRAM_WORDS = 512
IMM16_MIN, IMM16_MAX = -32768, 32767
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
VAR_MIN, VAR_MAX = -32768, 32767


class Op(IntEnum):
    NOP = 0x00
    ADD = 0x01
    SUB = 0x02
    MUL = 0x03
    DIV = 0x04
    CMP_GT = 0x05
    CMP_LT = 0x06
    AND = 0x07
    OR = 0x08
    LOAD_IMM = 0x09
    JMP = 0x0A
    JMP_IF = 0x0B
    ASSIGNVAR = 0x0C
    GETVAR = 0x0D
    GETBALANCE = 0x0E
    GETSTOCKPRICE = 0x0F
    GETSTOCKPRICEBEFORE = 0x10
    GETSUMPRICEBEFORE = 0x11
    UPDATEBALANCE = 0x12
    UPDATEALLSTOCKBUFFERS = 0x13
    HALT = 0x14
    CMP_GTE = 0x15
    CMP_LTE = 0x16
    SELECT = 0x17
    SETBALANCE = 0x18
    EMITDECISION = 0x19
    EMITBALANCE = 0x1A


# The spec lists these, but control_unit.v never writes their results back
# (and alu.v doesn't compute them), so on real hardware they silently do nothing.
NOT_IN_RTL = frozenset({Op.AND, Op.OR, Op.HALT, Op.CMP_GTE, Op.CMP_LTE, Op.SELECT})
IMPLEMENTED = frozenset(Op) - NOT_IN_RTL

TWO_WORD = frozenset({Op.LOAD_IMM, Op.JMP, Op.JMP_IF})

# Operand order in assembly text. Field names match Instr attributes.
#   rd/rs1/rs2/rs3 -> R0..R7    var -> VAR1..VAR15 (var_id + 1, spec section 5)
#   buf -> BUF0..BUF4           imm5 -> 0..31      imm -> 16-bit signed
#   target -> label or absolute address
SIGNATURES: dict[Op, tuple[str, ...]] = {
    Op.NOP: (),
    Op.ADD: ("rd", "rs1", "rs2"),
    Op.SUB: ("rd", "rs1", "rs2"),
    Op.MUL: ("rd", "rs1", "rs2"),
    Op.DIV: ("rd", "rs1", "rs2"),
    Op.CMP_GT: ("rd", "rs1", "rs2"),
    Op.CMP_LT: ("rd", "rs1", "rs2"),
    Op.AND: ("rd", "rs1", "rs2"),
    Op.OR: ("rd", "rs1", "rs2"),
    Op.LOAD_IMM: ("rd", "imm"),
    Op.JMP: ("target",),
    Op.JMP_IF: ("rs1", "target"),
    Op.ASSIGNVAR: ("var", "rs1"),
    Op.GETVAR: ("rd", "var"),
    Op.GETBALANCE: ("rd",),
    Op.GETSTOCKPRICE: ("rd", "buf"),
    Op.GETSTOCKPRICEBEFORE: ("rd", "buf", "imm5"),
    Op.GETSUMPRICEBEFORE: ("rd", "buf", "imm5"),
    Op.UPDATEBALANCE: ("rs1", "buf"),
    Op.UPDATEALLSTOCKBUFFERS: (),
    Op.HALT: (),
    Op.CMP_GTE: ("rd", "rs1", "rs2"),
    Op.CMP_LTE: ("rd", "rs1", "rs2"),
    Op.SELECT: ("rd", "rs1", "rs2", "rs3"),
    Op.SETBALANCE: ("rs1",),
    Op.EMITDECISION: ("rs1", "buf", "imm5"),
    Op.EMITBALANCE: ("rs1",),
}


@dataclass
class Instr:
    op: Op
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    rs3: int = 0
    var: int = 0
    buf: int = 0
    imm5: int = 0
    imm: int = 0
    target: str | int | None = None
    comment: str = ""

    @property
    def size(self) -> int:
        return 2 if self.op in TWO_WORD else 1


@dataclass
class Label:
    name: str
    comment: str = ""


Item = Instr | Label


class EncodingError(ValueError):
    pass


def _check(name: str, value: int, lo: int, hi: int) -> int:
    if not lo <= value <= hi:
        raise EncodingError(f"{name}={value} out of range [{lo}, {hi}]")
    return value


def encode(instr: Instr, labels: dict[str, int] | None = None) -> list[int]:
    """Encode one instruction into 1 or 2 32-bit words (spec section 3)."""
    op = instr.op
    rd = _check("rd", instr.rd, 0, NUM_REGS - 1)
    rs1 = _check("rs1", instr.rs1, 0, NUM_REGS - 1)
    rs2 = _check("rs2", instr.rs2, 0, NUM_REGS - 1)
    var = _check("var_id", instr.var, 0, NUM_VARS - 1)
    buf = _check("buf_id", instr.buf, 0, NUM_BUFFERS - 1)
    imm5 = _check("imm5", instr.imm5, 0, 31)

    if op == Op.SELECT:
        buf = _check("rs3", instr.rs3, 0, NUM_REGS - 1)
    if op == Op.JMP_IF:
        # RTL reads the condition from Rs1; mirror it into Rd too, same as the
        # hardware team's bring-up assembler, so either reading works.
        rd = rs1

    word0 = (
        (int(op) << 27)
        | (rd << 24)
        | (rs1 << 21)
        | (rs2 << 18)
        | (var << 14)
        | (buf << 11)
        | (imm5 << 6)
    )
    if op == Op.LOAD_IMM:
        return [word0, _check("imm16", instr.imm, IMM16_MIN, IMM16_MAX) & 0xFFFF]
    if op in (Op.JMP, Op.JMP_IF):
        target = instr.target
        if isinstance(target, str):
            if labels is None or target not in labels:
                raise EncodingError(f"undefined label {target!r}")
            target = labels[target]
        if target is None:
            raise EncodingError(f"{op.name} needs a target")
        return [word0, _check("addr", target, 0, PROGRAM_WORDS - 1)]
    return [word0]


def decode(words: list[int], at: int = 0) -> Instr:
    """Decode the instruction starting at words[at]."""
    w = words[at]
    op = Op((w >> 27) & 0x1F)
    ins = Instr(
        op=op,
        rd=(w >> 24) & 7,
        rs1=(w >> 21) & 7,
        rs2=(w >> 18) & 7,
        var=(w >> 14) & 0xF,
        buf=(w >> 11) & 7,
        imm5=(w >> 6) & 0x1F,
    )
    if op == Op.SELECT:
        ins.rs3 = ins.buf
    if op == Op.LOAD_IMM:
        raw = words[at + 1] & 0xFFFF
        ins.imm = raw - 0x10000 if raw & 0x8000 else raw
    elif op in (Op.JMP, Op.JMP_IF):
        ins.target = words[at + 1] & 0x1FF
    return ins


def load_program_message(words: list[int]) -> bytes:
    """UART LOAD_PROGRAM frame (spec section 6.1): 0x01, uint16 length, LE words."""
    body = b"".join((w & 0xFFFFFFFF).to_bytes(4, "little") for w in words)
    if len(body) > PROGRAM_WORDS * 4:
        raise EncodingError(f"program is {len(words)} words, max {PROGRAM_WORDS}")
    return bytes([0x01]) + len(body).to_bytes(2, "little") + body


def tick_message(buf: int, price: int) -> bytes:
    """UART TICK frame (spec section 6.2)."""
    _check("buf_id", buf, 0, NUM_BUFFERS - 1)
    _check("price", price, IMM16_MIN, IMM16_MAX)
    return bytes([0x02, buf]) + price.to_bytes(2, "little", signed=True)
