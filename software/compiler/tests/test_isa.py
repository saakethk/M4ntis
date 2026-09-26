import unittest

from helpers import sys  # noqa: F401  (sets up sys.path)

import json
from pathlib import Path

from tradecpu import compile_strategy
from tradecpu.asm import assemble, disassemble, format_asm, parse_asm
from tradecpu.isa import Instr, Op, decode, encode, load_program_message, tick_message

EXAMPLES = Path(__file__).resolve().parents[2] / "frontend" / "dev-sketchout" / "examples"

# hardware/python/balance_test.py's program, written as assembly text.
BRINGUP = """
    LOAD_IMM R1, 10000
    LOAD_IMM R2, 100
    MUL R1, R1, R2
    SETBALANCE R1
    LOAD_IMM R0, 0
    LOAD_IMM R6, 10
    GETBALANCE R5
    EMITBALANCE R5
    UPDATEALLSTOCKBUFFERS
LOOP:
    UPDATEALLSTOCKBUFFERS
    GETSTOCKPRICE R1, BUF0
    GETSTOCKPRICEBEFORE R2, BUF0, 1
    CMP_GT R3, R1, R2
    JMP_IF R3, BUY
    CMP_LT R3, R1, R2
    JMP_IF R3, SELL
    JMP REPORT
BUY:
    MUL R4, R1, R6
    UPDATEBALANCE R4, BUF0
    EMITDECISION R6, BUF0, 1
    JMP REPORT
SELL:
    MUL R4, R1, R6
    SUB R4, R0, R4
    UPDATEBALANCE R4, BUF0
    EMITDECISION R6, BUF0, 0
REPORT:
    GETBALANCE R5
    EMITBALANCE R5
    JMP LOOP
"""


def bringup_reference_words() -> list[int]:
    """Re-implementation of the hardware team's encoder in balance_test.py."""
    OP = {"MUL": 0x03, "SUB": 0x02, "CMP_GT": 0x05, "CMP_LT": 0x06, "LOAD_IMM": 0x09, "JMP": 0x0A,
          "JMP_IF": 0x0B, "GETBALANCE": 0x0E, "GETSTOCKPRICE": 0x0F, "GETSTOCKPRICEBEFORE": 0x10,
          "UPDATEBALANCE": 0x12, "UPDATEALLSTOCKBUFFERS": 0x13, "SETBALANCE": 0x18,
          "EMITDECISION": 0x19, "EMITBALANCE": 0x1A}

    def word(op, rd=0, rs1=0, rs2=0, var=0, buf=0, imm5=0):
        return (OP[op] << 27) | (rd << 24) | (rs1 << 21) | (rs2 << 18) | (var << 14) | (buf << 11) | (imm5 << 6)

    src = [
        (None, "LOAD_IMM", dict(rd=1, imm=10000)), (None, "LOAD_IMM", dict(rd=2, imm=100)),
        (None, "MUL", dict(rd=1, rs1=1, rs2=2)), (None, "SETBALANCE", dict(rs1=1)),
        (None, "LOAD_IMM", dict(rd=0, imm=0)), (None, "LOAD_IMM", dict(rd=6, imm=10)),
        (None, "GETBALANCE", dict(rd=5)), (None, "EMITBALANCE", dict(rs1=5)),
        (None, "UPDATEALLSTOCKBUFFERS", {}),
        ("LOOP", "UPDATEALLSTOCKBUFFERS", {}), (None, "GETSTOCKPRICE", dict(rd=1, buf=0)),
        (None, "GETSTOCKPRICEBEFORE", dict(rd=2, buf=0, imm5=1)), (None, "CMP_GT", dict(rd=3, rs1=1, rs2=2)),
        (None, "JMP_IF", dict(rs1=3, to="BUY")), (None, "CMP_LT", dict(rd=3, rs1=1, rs2=2)),
        (None, "JMP_IF", dict(rs1=3, to="SELL")), (None, "JMP", dict(to="REPORT")),
        ("BUY", "MUL", dict(rd=4, rs1=1, rs2=6)), (None, "UPDATEBALANCE", dict(rs1=4, buf=0)),
        (None, "EMITDECISION", dict(rs1=6, buf=0, imm5=1)), (None, "JMP", dict(to="REPORT")),
        ("SELL", "MUL", dict(rd=4, rs1=1, rs2=6)), (None, "SUB", dict(rd=4, rs1=0, rs2=4)),
        (None, "UPDATEBALANCE", dict(rs1=4, buf=0)), (None, "EMITDECISION", dict(rs1=6, buf=0, imm5=0)),
        ("REPORT", "GETBALANCE", dict(rd=5)), (None, "EMITBALANCE", dict(rs1=5)), (None, "JMP", dict(to="LOOP")),
    ]
    labels, addr = {}, 0
    for label, op, _ in src:
        if label:
            labels[label] = addr
        addr += 2 if op in ("LOAD_IMM", "JMP", "JMP_IF") else 1
    words = []
    for _, op, orig in src:
        kw = dict(orig)
        second = None
        if op == "LOAD_IMM":
            second = kw.pop("imm") & 0xFFFF
        elif op in ("JMP", "JMP_IF"):
            second = labels[kw.pop("to")]
        if op == "JMP_IF":
            kw["rd"] = kw["rs1"]
        words.append(word(op, **kw))
        if second is not None:
            words.append(second)
    return words


class TestEncoding(unittest.TestCase):
    def test_matches_hardware_bringup_encoder(self):
        self.assertEqual(assemble(parse_asm(BRINGUP)).words, bringup_reference_words())

    def test_known_words(self):
        self.assertEqual(encode(Instr(Op.SETBALANCE, rs1=1)), [0xC0200000])
        self.assertEqual(encode(Instr(Op.LOAD_IMM, rd=3, imm=-1)), [0x4B000000, 0xFFFF])
        self.assertEqual(encode(Instr(Op.ASSIGNVAR, var=14, rs1=2)), [(0x0C << 27) | (2 << 21) | (14 << 14)])

    def test_decode_roundtrip(self):
        prog = assemble(parse_asm(BRINGUP))
        again = assemble(parse_asm(format_asm(disassemble(prog.words))))
        self.assertEqual(again.words, prog.words)

    def test_decode_sign_extends_imm(self):
        self.assertEqual(decode([0x4B000000, 0x8000]).imm, -32768)

    def test_listing_parses_back(self):
        prog = assemble(parse_asm(BRINGUP))
        self.assertEqual(assemble(parse_asm(prog.listing())).words, prog.words)

    def test_uart_frames(self):
        msg = load_program_message([0x11223344])
        self.assertEqual(msg, bytes([0x01, 4, 0, 0x44, 0x33, 0x22, 0x11]))
        self.assertEqual(tick_message(2, -2), bytes([0x02, 2, 0xFE, 0xFF]))

    def test_python_array_frames_like_balance_test(self):
        progs = [assemble(parse_asm(BRINGUP))]
        for path in sorted(EXAMPLES.glob("*.strategy.json")):
            progs.append(compile_strategy(json.loads(path.read_text())).assembled)
        for prog in progs:
            ns: dict = {}
            exec(prog.python_array(), ns)
            instructions = ns["instructions"]
            self.assertEqual(instructions, prog.words)
            # Framing copied from hardware/python/balance_test.py main().
            body = b"".join(w.to_bytes(4, "little") for w in instructions)
            frame = bytes([0x01]) + len(body).to_bytes(2, "little") + body
            self.assertEqual(frame, load_program_message(prog.words))

    def test_rejects_bad_operands(self):
        with self.assertRaises(ValueError):
            parse_asm("ASSIGNVAR VAR16, R0")
        with self.assertRaises(ValueError):
            parse_asm("GETSTOCKPRICE R0, BUF5")
        with self.assertRaises(ValueError):
            assemble(parse_asm("JMP NOWHERE"))


if __name__ == "__main__":
    unittest.main()
