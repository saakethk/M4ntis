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

    def test_equity_ends_higher_than_it_starts(self) -> None:
        balances = backtests.dummy_balances()
        self.assertLess(balances[0]["equity"], balances[-1]["equity"])
        self.assertEqual(balances[1]["cash"], 98_200.0)


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


if __name__ == "__main__":
    unittest.main()
