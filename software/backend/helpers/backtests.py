"""Store a pretend backtest for a strategy.

Nothing is simulated against market data. The run snapshots the strategy as it
exists now, then writes a fixed set of orders and balances.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from helpers.db import connect
from helpers.strategies import StrategyNotFound, can_view

START = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


class UserNotFound(Exception):
    pass


def dummy_orders() -> list[dict[str, Any]]:
    return [
        {
            "ts": START,
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "price": 180.0,
        },
        {
            "ts": START + timedelta(days=1),
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 10,
            "price": 186.0,
        },
    ]


def dummy_balances() -> list[dict[str, Any]]:
    return [
        {"ts": START, "cash": 100_000.0, "equity": 100_000.0},
        {"ts": START + timedelta(minutes=1), "cash": 98_200.0, "equity": 100_000.0},
        {
            "ts": START + timedelta(days=1),
            "cash": 100_060.0,
            "equity": 100_060.0,
        },
    ]


def dummy_menu() -> dict[str, Any]:
    """Fixed backtest menu. Nothing is read from the database."""
    orders = [_public_row(order) for order in dummy_orders()]
    balances = [_public_row(point) for point in dummy_balances()]
    start_equity = float(balances[0]["equity"])
    end_equity = float(balances[-1]["equity"])
    return_pct = 0.0 if start_equity == 0 else (end_equity - start_equity) / start_equity * 100
    return {
        "dummy": True,
        "equity": end_equity,
        "return_pct": round(return_pct, 2),
        "orders": orders,
        "balances": balances,
    }


def run_dummy_backtest(user_id: int, strategy_id: int) -> dict[str, Any]:
    """Record a dummy run of ``strategy_id`` for ``user_id``."""
    orders = dummy_orders()
    balances = dummy_balances()
    conn = connect()
    try:
        with conn.transaction():
            if conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is None:
                raise UserNotFound()
            strategy = conn.execute(
                """
                SELECT user_id, visibility, document, ir
                FROM strategies
                WHERE id = %s
                """,
                (strategy_id,),
            ).fetchone()
            if strategy is None or not can_view(int(strategy[0]), str(strategy[1]), user_id):
                raise StrategyNotFound()
            version = conn.execute(
                """
                INSERT INTO strategy_versions (strategy_id, document, ir)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    strategy_id,
                    Jsonb(strategy[2]),
                    Jsonb(strategy[3]) if strategy[3] is not None else None,
                ),
            ).fetchone()
            backtest = conn.execute(
                """
                INSERT INTO backtests (strategy_version_id, user_id)
                VALUES (%s, %s)
                RETURNING id
                """,
                (int(version[0]), user_id),
            ).fetchone()
            backtest_id = int(backtest[0])
            conn.executemany(
                """
                INSERT INTO backtest_orders (backtest_id, ts, symbol, side, quantity, price)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        backtest_id,
                        order["ts"],
                        order["symbol"],
                        order["side"],
                        order["quantity"],
                        order["price"],
                    )
                    for order in orders
                ],
            )
            conn.executemany(
                """
                INSERT INTO backtest_balances (backtest_id, ts, cash, equity)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (backtest_id, point["ts"], point["cash"], point["equity"])
                    for point in balances
                ],
            )
    finally:
        conn.close()
    return {
        "id": backtest_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "strategy_version_id": int(version[0]),
        "dummy": True,
        "orders": [_public_row(order) for order in orders],
        "balances": [_public_row(point) for point in balances],
    }


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = dict(row)
    copied["ts"] = copied["ts"].isoformat()
    return copied
