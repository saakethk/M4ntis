"""Backtest tests that do not require Tiger Data."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import dev.software.backend.helpers.backtests as backtests
import dev.software.backend.main as main
from dev.software.backend.helpers.auth import User


class DummySeriesTest(unittest.TestCase):
    def test_orders_are_a_buy_then_a_sell(self) -> None:
        orders = backtests.dummy_orders()
        self.assertEqual([order["side"] for order in orders], ["buy", "sell"])
        self.assertEqual(orders[0]["symbol"], "AAPL")

    def test_menu_is_fixed_and_does_not_touch_the_database(self) -> None:
        menu = backtests.dummy_menu()
        self.assertTrue(menu["dummy"])
        self.assertEqual(menu["equity"], 100_060.0)
        self.assertEqual(menu["return_pct"], 0.06)
        self.assertEqual(len(menu["orders"]), 2)
        self.assertEqual(len(menu["balances"]), 3)

    def test_equity_ends_higher_than_it_starts(self) -> None:
        balances = backtests.dummy_balances()
        self.assertLess(balances[0]["equity"], balances[-1]["equity"])
        self.assertEqual(balances[1]["cash"], 98_200.0)

    def test_performance_counts_the_winning_round_trip(self) -> None:
        orders = [backtests._public_row(order) for order in backtests.dummy_orders()]
        balances = [backtests._public_row(point) for point in backtests.dummy_balances()]
        metrics = backtests.performance(orders, balances)
        self.assertEqual(metrics["equity"], 100_060.0)
        self.assertEqual(metrics["return_pct"], 0.06)
        self.assertEqual(metrics["gross_pnl"], 60.0)
        self.assertEqual(metrics["max_drawdown_pct"], 0.0)
        self.assertEqual(metrics["num_trades"], 1)
        self.assertEqual(metrics["num_trades_won"], 1)
        self.assertEqual(metrics["num_trades_lost"], 0)
        self.assertEqual(metrics["avg_win_amount"], 60.0)
        self.assertEqual(metrics["trade_returns"], [60.0])
        self.assertIsNotNone(metrics["cagr_pct"])

    def test_performance_records_a_drawdown(self) -> None:
        balances = [
            {"ts": "2024-01-02T14:30:00+00:00", "cash": 100, "equity": 100},
            {"ts": "2024-01-02T14:31:00+00:00", "cash": 80, "equity": 80},
            {"ts": "2024-01-02T14:32:00+00:00", "cash": 90, "equity": 90},
        ]
        metrics = backtests.performance([], balances)
        self.assertEqual(metrics["max_drawdown_pct"], 20.0)
        self.assertEqual(metrics["num_trades"], 0)
        self.assertIsNone(metrics["avg_win_amount"])


EXAMPLES = Path(__file__).resolve().parents[1] / "frontend" / "dev-sketchout" / "examples"
T0 = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.strategy.json").read_text())


def bars(closes: list[float], symbol: str = "AAPL") -> list:
    return [(T0 + timedelta(minutes=5 * i), {symbol: close}) for i, close in enumerate(closes)]


class SimulateTest(unittest.TestCase):
    def test_rising_prices_trigger_buys_charged_at_the_close(self) -> None:
        result = backtests._compile(example("sma_crossover"), {})
        closes = [100 + i * 0.5 for i in range(40)]
        orders, balances = backtests.simulate(result.words, result.manifest, bars(closes))
        self.assertTrue(orders)
        self.assertEqual({order["side"] for order in orders}, {"buy"})
        first = orders[0]
        index = closes.index(first["price"])
        self.assertEqual(first["ts"], T0 + timedelta(minutes=5 * index))
        self.assertEqual(len(balances), len(closes))
        self.assertEqual(balances[0]["cash"], 100_000.0)
        spent = sum(order["price"] * order["quantity"] for order in orders)
        self.assertAlmostEqual(balances[-1]["cash"], 100_000.0 - spent, places=2)
        held = sum(order["quantity"] for order in orders)
        self.assertAlmostEqual(balances[-1]["equity"], balances[-1]["cash"] + held * closes[-1], places=2)

    def test_negative_cash_stops_the_run(self) -> None:
        result = backtests._compile(backtests._with_capital(example("sma_crossover"), 1_000), {})
        closes = [100 + i * 0.5 for i in range(40)]
        with self.assertRaises(backtests.NegativeCash) as caught:
            backtests.simulate(result.words, result.manifest, bars(closes))
        self.assertIn("Cash went negative", str(caught.exception))
        self.assertIn("AAPL", str(caught.exception))

    def test_selling_shares_not_held_stops_the_run(self) -> None:
        # Falling prices put the fast SMA under the slow one, so the crossover sells first.
        result = backtests._compile(example("sma_crossover"), {})
        closes = [200 - i * 0.5 for i in range(40)]
        with self.assertRaises(backtests.ShortSale) as caught:
            backtests.simulate(result.words, result.manifest, bars(closes))
        self.assertIn("tried to sell", str(caught.exception))
        self.assertIn("held 0", str(caught.exception))

    def test_selling_shares_that_are_held_is_allowed(self) -> None:
        # Rise long enough to buy, then fall so the crossover sells what it bought.
        result = backtests._compile(example("sma_crossover"), {})
        closes = [100 + i for i in range(32)] + [131 - i * 3 for i in range(1, 12)]
        orders, _ = backtests.simulate(result.words, result.manifest, bars(closes))
        self.assertIn("sell", {order["side"] for order in orders})
        held = 0
        for order in orders:
            held += order["quantity"] if order["side"] == "buy" else -order["quantity"]
            self.assertGreaterEqual(held, 0)

    def test_negative_cash_is_not_stored(self) -> None:
        failure = backtests.NegativeCash("Cash went negative")
        with patch.object(backtests, "_load_strategy", return_value={"document": {}, "ir": None}):
            with patch.object(backtests, "_compile") as compile_mock:
                compile_mock.return_value.manifest = {
                    "resolution": "5m",
                    "buffers": [{"buf": 0, "symbol": "AAPL", "used": True}],
                }
                with patch.object(backtests, "_load_bars", return_value=bars([100.0])):
                    with patch.object(backtests, "simulate", side_effect=failure):
                        with patch.object(backtests, "_store_run") as store:
                            with self.assertRaises(backtests.NegativeCash):
                                backtests.run_backtest(4, 8)
        store.assert_not_called()

    def test_warm_up_bars_never_trade(self) -> None:
        result = backtests._compile(example("sma_crossover"), {})
        warmup = result.manifest["warmupTicks"]
        orders, _ = backtests.simulate(result.words, result.manifest, bars([100 + i for i in range(40)]))
        self.assertGreaterEqual(orders[0]["ts"], T0 + timedelta(minutes=5 * warmup))

    def test_too_few_bars_is_rejected(self) -> None:
        result = backtests._compile(example("sma_crossover"), {})
        with self.assertRaises(backtests.BacktestFailed):
            backtests.simulate(result.words, result.manifest, bars([100.0] * 3))

    def test_capital_overrides_the_starting_balance(self) -> None:
        document = example("sma_crossover")
        changed = backtests._with_capital(document, 2_500)
        result = backtests._compile(changed, {})
        self.assertEqual(result.manifest["startingBalance"], 2_500)
        start = next(node for node in document["flow"]["nodes"] if node["type"] == "start")
        self.assertEqual(start["data"]["params"]["startingBalance"], 100_000)

    def test_price_exponent_fits_int16(self) -> None:
        self.assertEqual(backtests._price_exponent("AAPL", bars([180.0])), 2)
        self.assertEqual(backtests._price_exponent("AAPL", bars([900.0])), 1)
        self.assertEqual(backtests._price_exponent("AAPL", bars([5_000.0])), 0)
        with self.assertRaises(backtests.BacktestFailed):
            backtests._price_exponent("AAPL", bars([40_000.0]))

    def test_equity_path_is_thinned_but_keeps_the_last_point(self) -> None:
        path = [{"ts": T0, "cash": i, "equity": i} for i in range(1_234)]
        thinned = backtests._thin(path, 500)
        self.assertLessEqual(len(thinned), 501)
        self.assertIs(thinned[0], path[0])
        self.assertIs(thinned[-1], path[-1])

    def test_bars_are_aligned_across_symbols(self) -> None:
        def stream(symbol, resolution, since, until):
            self.assertEqual(resolution, "5min")
            self.assertEqual(since.isoformat(), "2024-01-02T00:00:00-05:00")
            self.assertEqual(until.isoformat(), "2024-01-04T00:00:00-05:00")
            times = [T0, T0 + timedelta(minutes=5)] if symbol == "AAPL" else [T0 + timedelta(minutes=5)]
            return [{"ts": ts, "close": 10.0} for ts in times]

        with patch.object(backtests, "stream_ticker_data", side_effect=stream):
            aligned = backtests._load_bars(
                {0: "AAPL", 1: "MSFT"}, "5m", date(2024, 1, 2), date(2024, 1, 3)
            )
        self.assertEqual(aligned, [(T0 + timedelta(minutes=5), {"AAPL": 10.0, "MSFT": 10.0})])


class BacktestRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)
        self.client.cookies.set("session", "raw-token")

    def test_run_passes_the_parameters_through(self) -> None:
        payload = {
            "id": 3,
            "user_id": 4,
            "strategy_id": 8,
            "strategy_version_id": 11,
            "dummy": False,
            "orders": [],
            "balances": [],
        }
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "run_backtest", return_value=payload) as run:
                response = self.client.post(
                    "/backtests",
                    json={
                        "user_id": 4,
                        "strategy_id": 8,
                        "start": "2024-01-02",
                        "end": "2024-06-28",
                        "capital": 50000,
                    },
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["dummy"], False)
        run.assert_called_once_with(
            4, 8, start=date(2024, 1, 2), end=date(2024, 6, 28), capital=50000.0
        )

    def test_parameters_are_optional(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "run_backtest", return_value={"id": 1}) as run:
                response = self.client.post("/backtests", json={"user_id": 4, "strategy_id": 8})
        self.assertEqual(response.status_code, 201)
        run.assert_called_once_with(4, 8, start=None, end=None, capital=None)

    def test_compile_errors_return_diagnostics(self) -> None:
        failure = main.compiler.CompilationFailed([{"level": "error", "message": "bad", "node": "n1"}])
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "run_backtest", side_effect=failure):
                response = self.client.post("/backtests", json={"user_id": 4, "strategy_id": 8})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["diagnostics"][0]["node"], "n1")

    def test_a_failed_run_is_a_bad_request(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(
                backtests, "run_backtest", side_effect=backtests.BacktestFailed("No market data")
            ):
                response = self.client.post("/backtests", json={"user_id": 4, "strategy_id": 8})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "No market data")

    def test_capital_must_be_positive(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post(
                "/backtests", json={"user_id": 4, "strategy_id": 8, "capital": 0}
            )
        self.assertEqual(response.status_code, 422)

    def test_user_id_must_be_the_signed_in_user(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.post(
                "/backtests",
                json={"user_id": 9, "strategy_id": 8},
            )
        self.assertEqual(response.status_code, 403)

    def test_menu_requires_a_session(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=None):
            response = self.client.get("/backtests/dummy")
        self.assertEqual(response.status_code, 401)

    def test_menu_route_returns_the_dummy_series(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            response = self.client.get("/backtests/dummy")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["dummy"], True)
        self.assertEqual(body["orders"][0]["side"], "buy")
        self.assertEqual(body["balances"][-1]["equity"], 100_060.0)

    def test_get_returns_the_stored_run_for_the_session_user(self) -> None:
        stored = {
            "id": 3,
            "strategy_id": 8,
            "strategy_name": "Opening Drive",
            "metrics": {"equity": 100_060.0},
        }
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "get_backtest", return_value=stored) as fetch:
                response = self.client.get("/backtests/3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["strategy_name"], "Opening Drive")
        fetch.assert_called_once_with(4, 3)

    def test_get_hides_a_missing_backtest(self) -> None:
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "get_backtest", side_effect=backtests.BacktestNotFound()):
                response = self.client.get("/backtests/99")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
