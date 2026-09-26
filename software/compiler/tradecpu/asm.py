"""Assembly text format, two-pass assembler, and disassembler.

Syntax (one statement per line, `;` starts a comment):

    LOOP:                               ; label
        UPDATEALLSTOCKBUFFERS
        GETSTOCKPRICEBEFORE R2, BUF0, 1
        LOAD_IMM R3, -250
        ASSIGNVAR VAR1, R2              ; VAR1..VAR15 -> var_id 0..14
        JMP_IF R3, LOOP
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .isa import (
    NUM_BUFFERS,
    NUM_REGS,
    NUM_VARS,
    PROGRAM_WORDS,
    SIGNATURES,
    TWO_WORD,
    EncodingError,
    Instr,
    Item,
    Label,
    Op,
    decode,
    encode,
)


class AsmError(ValueError):
    pass


def format_operand(field: str, ins: Instr) -> str:
    if field in ("rd", "rs1", "rs2", "rs3"):
        return f"R{getattr(ins, field)}"
    if field == "var":
        return f"VAR{ins.var + 1}"
    if field == "buf":
        return f"BUF{ins.buf}"
    if field == "imm5":
        return str(ins.imm5)
    if field == "imm":
        return str(ins.imm)
    if field == "target":
        return str(ins.target)
    raise AssertionError(field)


def format_instr(ins: Instr) -> str:
    ops = ", ".join(format_operand(f, ins) for f in SIGNATURES[ins.op])
    return f"{ins.op.name} {ops}".rstrip()


def format_asm(items: list[Item], addresses: bool = False) -> str:
    """Render items as assembly text. With `addresses`, prefix each instruction with its word address."""
    lines: list[str] = []
    addr = 0
    for it in items:
        if isinstance(it, Label):
            lines.append(f"{it.name}:" + (f"  ; {it.comment}" if it.comment else ""))
            continue
        text = format_instr(it)
        prefix = f"{addr:4d}  " if addresses else "    "
        line = f"{prefix}{text:<36}"
        if it.comment:
            line += f"; {it.comment}"
        lines.append(line.rstrip())
        addr += it.size
    return "\n".join(lines) + "\n"


_REG = re.compile(r"^R([0-7])$", re.I)
_VAR = re.compile(r"^VAR(\d+)$", re.I)
_BUF = re.compile(r"^BUF(\d+)$", re.I)
_LABEL = re.compile(r"^[A-Za-z_.][\w.]*$")


def _parse_int(tok: str) -> int:
    return int(tok.lstrip("#"), 0)


def _parse_operand(field: str, tok: str, lineno: int):
    def fail(msg: str):
        raise AsmError(f"line {lineno}: {msg} (got {tok!r})")

    if field in ("rd", "rs1", "rs2", "rs3"):
        m = _REG.match(tok)
        return int(m.group(1)) if m else fail(f"expected register R0-R{NUM_REGS - 1}")
    if field == "var":
        m = _VAR.match(tok)
        if not m or not 1 <= int(m.group(1)) <= NUM_VARS:
            fail(f"expected VAR1-VAR{NUM_VARS}")
        return int(m.group(1)) - 1
    if field == "buf":
        m = _BUF.match(tok)
        if not m or not 0 <= int(m.group(1)) < NUM_BUFFERS:
            fail(f"expected BUF0-BUF{NUM_BUFFERS - 1}")
        return int(m.group(1))
    if field in ("imm5", "imm"):
        try:
            return _parse_int(tok)
        except ValueError:
            fail("expected integer")
    if field == "target":
        try:
            return _parse_int(tok)
        except ValueError:
            return tok if _LABEL.match(tok) else fail("expected label or address")
    raise AssertionError(field)


def parse_asm(text: str) -> list[Item]:
    items: list[Item] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        code, _, comment = raw.partition(";")
        code = code.strip()
        comment = comment.strip()
        while code:
            head, sep, rest = code.partition(":")
            if sep and _LABEL.match(head.strip()) and " " not in head.strip():
                items.append(Label(head.strip()))
                code = rest.strip()
                continue
            break
        if not code:
            continue
        # Tolerate the listing format's leading address column.
        code = re.sub(r"^\d+\s+", "", code)
        mnemonic, _, operand_text = code.partition(" ")
        try:
            op = Op[mnemonic.upper()]
        except KeyError:
            raise AsmError(f"line {lineno}: unknown mnemonic {mnemonic!r}") from None
        toks = [t.strip() for t in operand_text.split(",") if t.strip()]
        fields = SIGNATURES[op]
        if len(toks) != len(fields):
            raise AsmError(
                f"line {lineno}: {op.name} takes {len(fields)} operand(s) ({', '.join(fields)}), got {len(toks)}"
            )
        ins = Instr(op=op, comment=comment)
        for f, t in zip(fields, toks):
            setattr(ins, f, _parse_operand(f, t, lineno))
        items.append(ins)
    return items


@dataclass
class Assembled:
    words: list[int]
    labels: dict[str, int]
    items: list[Item]

    def listing(self) -> str:
        return format_asm(self.items, addresses=True)

    def hex_lines(self) -> str:
        return "".join(f"{w:08X}\n" for w in self.words)

    def python_array(self, name: str = "instructions") -> str:
        """Words as a Python list literal, in the shape hardware/python/balance_test.py sends."""
        lines = [f"{name} = ["]
        addr = 0
        pending_label = ""
        for it in self.items:
            if isinstance(it, Label):
                pending_label = it.name
                continue
            tag = f"{pending_label}: " if pending_label else ""
            pending_label = ""
            lines.append(f"    0x{self.words[addr]:08X},  # word {addr:3d}  {tag}{format_instr(it)}")
            if it.size == 2:
                lines.append(f"    0x{self.words[addr + 1]:08X},  # word {addr + 1:3d}    (operand word)")
            addr += it.size
        lines.append("]")
        return "\n".join(lines) + "\n"


def assemble(items: list[Item]) -> Assembled:
    labels: dict[str, int] = {}
    addr = 0
    for it in items:
        if isinstance(it, Label):
            if it.name in labels:
                raise AsmError(f"duplicate label {it.name!r}")
            labels[it.name] = addr
        else:
            addr += it.size
    if addr > PROGRAM_WORDS:
        raise AsmError(f"program is {addr} words; program memory holds {PROGRAM_WORDS}")
    words: list[int] = []
    for it in items:
        if isinstance(it, Instr):
            try:
                words.extend(encode(it, labels))
            except EncodingError as e:
                raise AsmError(f"{format_instr(it)}: {e}") from None
    return Assembled(words=words, labels=labels, items=items)


def disassemble(words: list[int]) -> list[Item]:
    """Words -> items, with synthetic labels `L<addr>` at jump targets."""
    decoded: list[tuple[int, Instr]] = []
    at = 0
    while at < len(words):
        ins = decode(words, at)
        decoded.append((at, ins))
        at += 2 if ins.op in TWO_WORD else 1
    targets = {ins.target for _, ins in decoded if isinstance(ins.target, int)}
    items: list[Item] = []
    for addr, ins in decoded:
        if addr in targets:
            items.append(Label(f"L{addr}"))
        if isinstance(ins.target, int):
            ins.target = f"L{ins.target}"
        items.append(ins)
    return items


def peephole(items: list[Item]) -> list[Item]:
    """Drop `JMP X` when X labels the very next instruction."""
    out: list[Item] = []
    for i, it in enumerate(items):
        if isinstance(it, Instr) and it.op == Op.JMP and isinstance(it.target, str):
            j = i + 1
            following: set[str] = set()
            while j < len(items) and isinstance(items[j], Label):
                following.add(items[j].name)  # type: ignore[union-attr]
                j += 1
            if it.target in following:
                continue
        out.append(it)
    return out
