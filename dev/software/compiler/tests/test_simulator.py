import unittest

from dev.software.compiler.tests.helpers import sys  # noqa: F401

from dev.software.compiler.tradecpu.asm import assemble, parse_asm
from dev.software.compiler.tradecpu.simulator import BalanceMsg, Decision, SimError, TradeCPU, div_trunc, run_rounds
from dev.software.compiler.tests.test_isa import BRINGUP


def run(src: str) -> TradeCPU:
    cpu = TradeCPU(assemble(parse_asm(src + "\nEND: JMP END\n")).words)
    for _ in range(10_000):
        if cpu.pc == cpu.words.__len__() - 2:
            break
        cpu.step()
    return cpu


class TestSemantics(unittest.TestCase):
    def test_div_truncates_toward_zero_and_by_zero_is_zero(self):
        self.assertEqual(div_trunc(-100, 7), -14)
        self.assertEqual(div_trunc(100, -7), -14)
        self.assertEqual(div_trunc(5, 0), 0)

    def test_var_store_truncates_to_16_bits(self):
        cpu = run("LOAD_IMM R0, 30000\nADD R0, R0, R0\nASSIGNVAR VAR1, R0\nGETVAR R1, VAR1")
        self.assertEqual(cpu.regs[1], 60000 - 65536)

    def test_unimplemented_opcode_is_rejected(self):
        with self.assertRaises(SimError):
            run("CMP_GTE R0, R1, R2")

    def test_buffer_wraparound_and_sum(self):
        words = assemble(parse_asm("""
        LOOP: UPDATEALLSTOCKBUFFERS
              GETSTOCKPRICEBEFORE R1, BUF0, 29
              GETSUMPRICEBEFORE R2, BUF0, 30
              EMITBALANCE R1
              EMITBALANCE R2
              JMP LOOP
        """)).words
        rounds = [[i + 1, 0, 0, 0, 0] for i in range(31)]
        _, per_round, _ = run_rounds(words, rounds)
        last = per_round[-1]
        self.assertEqual(last[0], BalanceMsg(2))  # 29 ticks before tick 31
        self.assertEqual(last[1], BalanceMsg(sum(range(2, 32))))

    def test_hardware_bringup_program(self):
        prices = [1000, 1010, 1005, 1005, 1020, 990]
        rounds = [[p, 500, 500, 500, 500] for p in prices]
        at_load, per_round, _ = run_rounds(assemble(parse_asm(BRINGUP)).words, rounds)
        self.assertEqual(at_load, [BalanceMsg(1_000_000)])
        self.assertEqual(per_round[0], [])
        self.assertEqual(per_round[1], [Decision(0, "buy", 10), BalanceMsg(1_000_000 - 10100)])
        self.assertEqual(per_round[3], [BalanceMsg(1_000_000 - 10100 + 10050)])


if __name__ == "__main__":
    unittest.main()
