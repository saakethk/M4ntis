"""Dummy backtest tests that do not require Tiger Data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import helpers.backtests as backtests
import main
from helpers.auth import User


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


class BacktestRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)
        self.client.cookies.set("session", "raw-token")

    def test_run_returns_the_dummy_result(self) -> None:
        payload = {
            "id": 3,
            "user_id": 4,
            "strategy_id": 8,
            "strategy_version_id": 11,
            "dummy": True,
            "orders": [],
            "balances": [],
        }
        with patch.object(main.auth, "user_from_token", return_value=User(4, "a@b.com")):
            with patch.object(backtests, "run_dummy_backtest", return_value=payload) as run:
                response = self.client.post(
                    "/backtests",
                    json={"user_id": 4, "strategy_id": 8},
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["dummy"], True)
        run.assert_called_once_with(4, 8)

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
