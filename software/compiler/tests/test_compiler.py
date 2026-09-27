import math
import random
import unittest

from helpers import Doc, only_rtl_ops

from tradecpu.compiler import CompileError, CompileOptions, compile_strategy, compile_to_json
from tradecpu.simulator import BalanceMsg, Decision, TradeCPU, run_rounds


def rounds_for(prices: list[int]) -> list[list[int]]:
    return [[p, 0, 0, 0, 0] for p in prices]


def random_walk(n: int, start: int = 15000, seed: int = 7) -> list[int]:
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p = max(100, p + rng.randint(-150, 150))
        out.append(p)
    return out


def sma_crossover(fast: int, slow: int, qty: int = 10) -> Doc:
    d = Doc()
    d.add("fast", "sma", n=fast)
    d.add("slow", "sma", n=slow)
    d.add("if1", "if", operator=">")
    d.add("buy", "buy", quantity=qty)
    d.add("sell", "sell", quantity=qty)
    d.exec("start", "if1").data("fast", "if1", "a").data("slow", "if1", "b")
    d.exec("if1", "buy", "then").exec("if1", "sell", "else")
    return d


def run_until_ticks(words: list[int], prices: list[int]) -> TradeCPU:
    cpu = TradeCPU(words)
    cpu.run_until_blocked()
    for p in prices:
        for b, v in enumerate([p, 0, 0, 0, 0]):
            cpu.tick(b, v)
        cpu.run_until_blocked()
    return cpu


class TestProgramShape(unittest.TestCase):
    def test_empty_strategy_only_acks(self):
        r = compile_strategy(Doc().json())
        at_load, per_round, _ = run_rounds(r.words, rounds_for([100, 101]))
        self.assertEqual(at_load, [BalanceMsg(10_000_000)])
        self.assertEqual(per_round, [[BalanceMsg(10_000_000)]] * 2)

    def test_warmup_matches_longest_lookback(self):
        r = compile_strategy(sma_crossover(3, 12).json())
        self.assertEqual(r.manifest["historyTicks"], 12)
        self.assertEqual(r.manifest["warmupTicks"], 11)
        _, per_round, _ = run_rounds(r.words, rounds_for(random_walk(14)))
        for msgs in per_round[:11]:
            self.assertEqual(len(msgs), 1)
        for msgs in per_round[11:]:
            self.assertIsInstance(msgs[0], Decision)

    def test_large_starting_balance(self):
        r = compile_strategy(Doc(startingBalance=1_234_567.89).json())
        at_load, _, _ = run_rounds(r.words, [])
        self.assertEqual(at_load, [BalanceMsg(123_456_789)])

    def test_get_ticker_supplies_the_symbol(self):
        d = Doc(symbol0="")
        d.add("tick", "get_ticker", symbol="aapl")
        d.add("fast", "sma", n=5, buffer=0)
        d.add("slow", "sma", n=8, buffer=0)
        d.add("if1", "if", operator=">")
        d.add("buy", "buy", quantity=1)
        d.add("sell", "sell", quantity=1)
        d.exec("start", "if1").data("fast", "if1", "a").data("slow", "if1", "b")
        d.exec("if1", "buy", "then").exec("if1", "sell", "else")
        r = compile_strategy(d.json())
        self.assertEqual(r.manifest["buffers"][0]["symbol"], "AAPL")
        self.assertTrue(r.manifest["buffers"][0]["used"])

    def test_price_n_ticks_ago_symbol_gets_its_own_buffer(self):
        d = Doc(symbol0="")
        d.add("tick", "get_ticker", symbol="AAPL")
        d.add("ago", "price_n_ticks_ago", symbol="nvda", n=3, buffer=0)
        d.add("if1", "if", operator=">")
        d.add("buy", "buy", quantity=1, buffer=0)
        d.add("const", "constant", value=1)
        d.exec("start", "if1").data("ago", "if1", "a").data("const", "if1", "b")
        d.exec("if1", "buy", "then")
        r = compile_strategy(d.json())
        self.assertEqual(r.manifest["buffers"][0]["symbol"], "AAPL")
        self.assertEqual(r.manifest["buffers"][1]["symbol"], "NVDA")
        self.assertTrue(r.manifest["buffers"][1]["used"])
        self.assertIn("GETSTOCKPRICEBEFORE", r.asm)
        self.assertIn("BUF1", r.asm)

    def test_only_rtl_opcodes(self):
        r = compile_strategy(sma_crossover(5, 20).json())
        self.assertTrue(only_rtl_ops(r.items))


class TestBehaviour(unittest.TestCase):
    def test_sma_crossover_matches_reference(self):
        fast, slow, qty = 5, 20, 10
        prices = random_walk(200)
        r = compile_strategy(sma_crossover(fast, slow, qty).json())
        _, per_round, _ = run_rounds(r.words, rounds_for(prices))

        cash = 10_000_000
        for t in range(slow - 1, len(prices)):
            f = sum(prices[t - fast + 1 : t + 1]) // fast
            s = sum(prices[t - slow + 1 : t + 1]) // slow
            p = prices[t]
            if f > s:
                cash -= p * qty
                want = [Decision(0, "buy", qty), BalanceMsg(cash)]
            else:
                cash += p * qty
                want = [Decision(0, "sell", qty), BalanceMsg(cash)]
            self.assertEqual(per_round[t], want, f"tick {t}")

    def test_all_comparison_operators(self):
        # price (cents) vs Constant 10.25 (dollars) -> compared as 1025 cents
        cases = {">": [1026], "<": [1024], ">=": [1025, 1026], "<=": [1024, 1025], "==": [1025], "!=": [1024, 1026]}
        for op, true_prices in cases.items():
            d = Doc()
            d.add("p", "current_price")
            d.add("c", "constant", value=10.25)
            d.add("if1", "if", operator=op)
            d.add("buy", "buy", quantity=1)
            d.add("sell", "sell", quantity=1)
            d.exec("start", "if1").data("p", "if1", "a").data("c", "if1", "b")
            d.exec("if1", "buy", "then").exec("if1", "sell", "else")
            r = compile_strategy(d.json())
            prices = [1024, 1025, 1026]
            _, per_round, _ = run_rounds(r.words, rounds_for(prices))
            for p, msgs in zip(prices, per_round):
                self.assertEqual(msgs[0].action, "buy" if p in true_prices else "sell", f"{p} {op} 10.25")

    def test_nested_if_is_and_chained_else_is_or(self):
        # sell if p < 500 OR p > 3000 (chained Else), else buy if p > 1000 AND p < 2000 (nested Then)
        d = Doc()
        d.add("p", "current_price")
        for nid, v in [("lo", 10), ("hi", 20), ("vlo", 5), ("vhi", 30)]:
            d.add(nid, "constant", value=v)
        d.add("if_lo", "if", operator=">")
        d.add("if_hi", "if", operator="<")
        d.add("if_vlo", "if", operator="<")
        d.add("if_vhi", "if", operator=">")
        d.add("buy", "buy", quantity=1)
        d.add("sell", "sell", quantity=1)
        d.data("p", "if_lo", "a").data("lo", "if_lo", "b").data("p", "if_hi", "a").data("hi", "if_hi", "b")
        d.data("p", "if_vlo", "a").data("vlo", "if_vlo", "b").data("p", "if_vhi", "a").data("vhi", "if_vhi", "b")
        d.exec("start", "if_vlo").exec("if_vlo", "sell", "then").exec("if_vlo", "if_vhi", "else")
        d.exec("if_vhi", "sell", "then").exec("if_vhi", "if_lo", "else")
        d.exec("if_lo", "if_hi", "then").exec("if_hi", "buy", "then")
        r = compile_strategy(d.json())
        prices = [1500, 2500, 400, 3500, 800]
        _, per_round, _ = run_rounds(r.words, rounds_for(prices))
        actions = [[m.action for m in msgs if isinstance(m, Decision)] for msgs in per_round]
        self.assertEqual(actions, [["buy"], [], ["sell"], ["sell"], []])

    def test_momentum(self):
        d = Doc()
        d.add("m", "momentum", n=3)
        d.add("c", "constant", value=0.05)
        d.add("if1", "if", operator=">")
        d.add("buy", "buy", quantity=1)
        d.exec("start", "if1").data("m", "if1", "a").data("c", "if1", "b").exec("if1", "buy", "then")
        r = compile_strategy(d.json())
        self.assertEqual(r.manifest["historyTicks"], 4)
        prices = [1000, 1000, 1000, 1051, 1000, 1000, 1000, 1049]
        _, per_round, _ = run_rounds(r.words, rounds_for(prices))
        for t in range(3, len(prices)):
            ratio = prices[t] * 100 // prices[t - 3] - 100
            bought = any(isinstance(m, Decision) for m in per_round[t])
            self.assertEqual(bought, ratio > 5, f"tick {t}")

    def test_volatility_matches_reference(self):
        n = 10
        d = Doc()
        d.add("v", "volatility", n=n)
        d.add("set", "set_var", slot="VAR1")
        d.exec("start", "set").data("v", "set", "value")
        r = compile_strategy(d.json())
        prices = random_walk(40, seed=3)
        cpu = run_until_ticks(r.words, prices)
        window = prices[-n:]
        mean = sum(window) // n
        var = sum((p - mean) ** 2 for p in window) // (n - 1)
        self.assertEqual(cpu.vars[0], math.isqrt(var))

    def test_sqrt_and_power(self):
        d = Doc()
        d.add("c", "constant", value=2)
        d.add("sq", "sqrt")
        d.add("pw", "power", exponent=3)
        d.add("set1", "set_var", slot="VAR1")
        d.add("set2", "set_var", slot="VAR2")
        d.data("c", "sq", "x").data("sq", "set1", "value").data("c", "pw", "base").data("pw", "set2", "value")
        d.exec("start", "set1").exec("set1", "set2")
        r = compile_strategy(d.json())
        cpu = run_until_ticks(r.words, [100])
        self.assertEqual(cpu.vars[0], 141)  # sqrt(2) = 1.41 at scale 10^2
        self.assertEqual(cpu.vars[1], 8)
        self.assertEqual(r.manifest["variableSlots"]["scales"], {"VAR1": 2})

    def test_for_loop_accumulates_within_one_tick(self):
        d = Doc()
        d.add("loop", "for", start=0, end=5, step=1)
        d.add("get", "get_var", slot="VAR1")
        d.add("add", "add")
        d.add("set", "set_var", slot="VAR1")
        d.exec("start", "loop").exec("loop", "set", "body")
        d.data("get", "add", "a").data("loop", "add", "b", src_port="index").data("add", "set", "value")
        r = compile_strategy(d.json())
        self.assertEqual(r.manifest["variableSlots"]["loopCounters"], {"loop": "VAR15"})
        self.assertEqual(run_until_ticks(r.words, [1]).vars[0], 10)
        self.assertEqual(run_until_ticks(r.words, [1, 1]).vars[0], 20)

    def test_divide_keeps_precision(self):
        # price / sum(2 ticks) at 1000,1000 = 0.5 -> 50 at scale 2, not truncated to 0
        d = Doc()
        d.add("p", "current_price")
        d.add("s", "sum_n_ticks", n=2)
        d.add("div", "divide")
        d.add("set", "set_var", slot="VAR1")
        d.data("p", "div", "a").data("s", "div", "b").data("div", "set", "value").exec("start", "set")
        cpu = run_until_ticks(compile_strategy(d.json()).words, [1000, 1000])
        self.assertEqual(cpu.vars[0], 50)

    def test_price_exponent_rescales_trade_cost(self):
        d = Doc()
        d.add("buy", "buy", quantity=3)
        d.exec("start", "buy")
        r = compile_strategy(d.json(), CompileOptions(price_exponents={0: 1}))
        _, per_round, _ = run_rounds(r.words, rounds_for([9000]))  # $900.0 in dimes
        self.assertEqual(per_round[0][-1], BalanceMsg(10_000_000 - 900_00 * 3))
        self.assertEqual([b["priceExponent"] for b in r.manifest["buffers"]], [1, 2, 2, 2, 2])

    def test_price_exponent_for_unknown_buffer_is_rejected(self):
        d = Doc()
        with self.assertRaisesRegex(CompileError, "BUF5"):
            compile_strategy(d.json(), CompileOptions(price_exponents={5: 1}))


class MalformedDocumentTest(unittest.TestCase):
    def test_wrong_json_shapes_become_diagnostics(self):
        schema = "m4ntis.strategy/v1"
        start = {"id": "start", "type": "start", "data": {"params": Doc().json()["flow"]["nodes"][0]["data"]["params"]}}
        cases = {
            "flow list": {"schema": schema, "flow": [1]},
            "flow string": {"schema": schema, "flow": "x"},
            "nodes object": {"schema": schema, "flow": {"nodes": {}, "edges": []}},
            "node number": {"schema": schema, "flow": {"nodes": [start, 1], "edges": []}},
            "data string": {"schema": schema, "flow": {"nodes": [start, {"id": "b", "type": "buy", "data": "x"}]}},
            "params list": {"schema": schema, "flow": {"nodes": [start, {"id": "b", "type": "buy", "data": {"params": [1]}}]}},
            "edge number": {"schema": schema, "flow": {"nodes": [start], "edges": [5]}},
            "type list": {"schema": schema, "flow": {"nodes": [start, {"id": "b", "type": ["buy"]}]}},
            "not a document": [1, 2],
        }
        for name, doc in cases.items():
            with self.subTest(name):
                with self.assertRaises(CompileError) as ctx:
                    compile_strategy(doc)
                self.assertTrue(ctx.exception.diagnostics)
                out = compile_to_json(doc)
                self.assertEqual(out["ok"], False)
                self.assertEqual(out["diagnostics"][0]["level"], "error")

    def test_compile_to_json_success_shape(self):
        out = compile_to_json(sma_crossover(3, 5).json())
        self.assertEqual(set(out), {"ok", "asm", "hex", "manifest", "diagnostics"})
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["hex"].split()), out["manifest"]["programWords"])

    def test_compile_to_json_points_at_the_bad_node(self):
        d = sma_crossover(3, 5)
        d.add("orphan", "sma", n=99)
        out = compile_to_json(d.json())
        self.assertFalse(out["ok"])
        self.assertIn({"level": "error", "message": "sma: n=99 out of range [1, 30]", "node": "orphan"}, out["diagnostics"])

    def test_mean_reversion_fits_program_memory(self):
        d = Doc()
        d.add("p", "current_price")
        d.add("bands", "mean_reversion_bands", n=30, k=2)
        d.add("if_lo", "if", operator="<=")
        d.add("if_hi", "if", operator=">=")
        d.add("buy", "buy")
        d.add("sell", "sell")
        d.exec("start", "if_lo").data("p", "if_lo", "a").data("bands", "if_lo", "b", src_port="lower")
        d.exec("if_lo", "buy", "then").exec("if_lo", "if_hi", "else")
        d.data("p", "if_hi", "a").data("bands", "if_hi", "b", src_port="upper").exec("if_hi", "sell", "then")
        r = compile_strategy(d.json())
        self.assertLessEqual(len(r.words), 512)
        prices = random_walk(80, seed=11)
        _, per_round, cycles = run_rounds(r.words, rounds_for(prices))
        self.assertTrue(any(isinstance(m, Decision) for msgs in per_round for m in msgs))
        self.assertLess(max(cycles), 50_000)  # 1 ms at 50 MHz


class TestErrors(unittest.TestCase):
    def assertCompileError(self, doc: dict, fragment: str):
        with self.assertRaises(CompileError) as ctx:
            compile_strategy(doc)
        self.assertIn(fragment, str(ctx.exception))

    def test_missing_input(self):
        d = Doc()
        d.add("if1", "if")
        d.exec("start", "if1")
        self.assertCompileError(d.json(), "not connected")

    def test_unassigned_symbol(self):
        d = Doc()
        d.add("buy", "buy", buffer=3)
        d.exec("start", "buy")
        self.assertCompileError(d.json(), "BUF3 is used but no Get ticker")

    def test_offset_beyond_buffer(self):
        d = Doc()
        d.add("p", "price_n_ticks_ago", n=30)
        d.add("set", "set_var")
        d.exec("start", "set").data("p", "set", "value")
        self.assertCompileError(d.json(), "out of range")

    def test_exec_loop(self):
        d = Doc()
        d.add("b1", "buy")
        d.add("b2", "buy")
        d.exec("start", "b1").exec("b1", "b2").exec("b2", "b1")
        self.assertCompileError(d.json(), "loop")

    def test_log_unsupported(self):
        d = Doc()
        d.add("c", "constant", value=10)
        d.add("lg", "log")
        d.add("set", "set_var")
        d.data("c", "lg", "x").data("c", "lg", "base").data("lg", "set", "value").exec("start", "set")
        self.assertCompileError(d.json(), "Log")

    def test_bad_document(self):
        self.assertCompileError({"schema": "nope"}, "m4ntis.strategy/v1")


if __name__ == "__main__":
    unittest.main()
