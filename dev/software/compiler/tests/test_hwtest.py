import unittest

from dev.software.compiler.tests.helpers import Doc  # noqa: F401  (sets up sys.path)

from dev.software.compiler.tradecpu import compile_strategy
from dev.software.compiler.tradecpu.hwtest import PATTERNS, FakeBoard, make_rounds, run_pattern
from dev.software.compiler.tradecpu.isa import IMM16_MAX, NUM_BUFFERS


def sma_crossover() -> dict:
    d = Doc()
    fast = d.add("fast", "sma", n=5)
    slow = d.add("slow", "sma", n=20)
    cond = d.add("cond", "if", operator=">")
    buy = d.add("buy", "buy")
    sell = d.add("sell", "sell")
    d.exec("start", cond)
    d.data(fast, cond, "a")
    d.data(slow, cond, "b")
    d.exec(cond, buy, "then")
    d.exec(cond, sell, "else")
    return d.json()


class OffByOneBoard(FakeBoard):
    """A board whose CMP_GT behaves like CMP_LT: swaps opcode 0x05 for 0x06 on load."""

    def write(self, data: bytes) -> int:
        if data[:1] == b"\x01":
            body = bytearray(data[3:])
            for i in range(0, len(body), 4):
                if body[i + 3] >> 3 == 0x05:
                    body[i + 3] = (0x06 << 3) | (body[i + 3] & 0x07)
            data = data[:3] + bytes(body)
        return super().write(data)


class HwTest(unittest.TestCase):
    def setUp(self):
        self.result = compile_strategy(sma_crossover())
        self.warmup = self.result.manifest["warmupTicks"]

    def test_patterns_fit_int16(self):
        for p in PATTERNS:
            rounds = make_rounds(p, 80, {b: 2 for b in range(NUM_BUFFERS)})
            self.assertEqual(len(rounds), 80)
            self.assertTrue(all(1 <= v <= IMM16_MAX for r in rounds for v in r), p)

    def test_dry_run_passes_and_trades(self):
        rounds = make_rounds("sine", self.warmup + 40, {})
        rep = run_pattern(FakeBoard(), self.result.words, rounds, "sine", self.warmup, tick_delay=0)
        self.assertEqual(rep.failures, 0, rep.lines)
        self.assertGreater(rep.buys, 0)
        self.assertGreater(rep.sells, 0)

    def test_stale_buffers_across_reloads_still_pass(self):
        board = FakeBoard()
        for p in ("walk", "steps"):
            rounds = make_rounds(p, self.warmup + 20, {})
            rep = run_pattern(board, self.result.words, rounds, p, self.warmup, tick_delay=0)
            self.assertEqual(rep.failures, 0, rep.lines)

    def test_detects_misbehaving_board(self):
        rounds = make_rounds("sine", self.warmup + 40, {})
        rep = run_pattern(OffByOneBoard(), self.result.words, rounds, "sine", self.warmup, tick_delay=0)
        self.assertGreater(rep.failures, 0)
        self.assertTrue(any("mismatch" in line for line in rep.lines))


if __name__ == "__main__":
    unittest.main()
