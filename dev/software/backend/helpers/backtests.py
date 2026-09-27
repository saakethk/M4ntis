"""Store a pretend backtest for a strategy.

Nothing is simulated against market data. The run snapshots the strategy as it
exists now, then writes a fixed set of orders and balances.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from dev.software.backend.helpers.db import connect
from dev.software.backend.helpers.strategies import StrategyNotFound, can_view

START = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


class UserNotFound(Exception):
    pass


class BacktestNotFound(Exception):
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


def performance(orders: list[dict[str, Any]], balances: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics the plan derives from orders and the equity path."""
    equities = [float(point["equity"]) for point in balances]
    start = equities[0] if equities else 0.0
    end = equities[-1] if equities else 0.0
    gross = end - start
    return_pct = 0.0 if start == 0 else (end - start) / start * 100
    peak = start
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    closed = _closed_trades(orders)
    wins = [pnl for pnl in closed if pnl > 0]
    losses = [pnl for pnl in closed if pnl < 0]
    return {
        "equity": end,
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "gross_pnl": round(gross, 2),
        "cagr_pct": _cagr_pct(balances, start, end),
        "sharpe": _sharpe(equities),
        "num_trades": len(closed),
        "num_trades_won": len(wins),
        "num_trades_lost": len(losses),
        "avg_win_amount": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_amount": round(sum(losses) / len(losses), 2) if losses else None,
        "expected_pnl_per_trade": round(sum(closed) / len(closed), 2) if closed else None,
        "trade_returns": [round(pnl, 2) for pnl in closed],
    }


def get_backtest(viewer_id: int, backtest_id: int) -> dict[str, Any]:
    """One stored run, including orders, balances, and derived metrics."""
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT b.id, b.user_id, b.created_at, b.strategy_version_id,
                   v.strategy_id, s.name, s.user_id, s.visibility
            FROM backtests b
            JOIN strategy_versions v ON v.id = b.strategy_version_id
            JOIN strategies s ON s.id = v.strategy_id
            WHERE b.id = %s
            """,
            (backtest_id,),
        ).fetchone()
        if row is None:
            raise BacktestNotFound()
        runner_id = int(row[1])
        if runner_id != viewer_id and not can_view(int(row[6]), str(row[7]), viewer_id):
            raise BacktestNotFound()
        order_rows = conn.execute(
            """
            SELECT ts, symbol, side, quantity, price
            FROM backtest_orders
            WHERE backtest_id = %s
            ORDER BY ts, id
            """,
            (backtest_id,),
        ).fetchall()
        balance_rows = conn.execute(
            """
            SELECT ts, cash, equity
            FROM backtest_balances
            WHERE backtest_id = %s
            ORDER BY ts, id
            """,
            (backtest_id,),
        ).fetchall()
    finally:
        conn.close()
    orders = [_order_row(item) for item in order_rows]
    balances = [_balance_row(item) for item in balance_rows]
    return {
        "id": int(row[0]),
        "user_id": runner_id,
        "strategy_id": int(row[4]),
        "strategy_name": str(row[5]),
        "strategy_version_id": int(row[3]),
        "created_at": row[2].isoformat(),
        "dummy": True,
        "orders": orders,
        "balances": balances,
        "metrics": performance(orders, balances),
    }


def run_dummy_backtest(user_id: int, strategy_id: int) -> dict[str, Any]:
    """Record a dummy run of ``strategy_id`` for ``user_id``."""
    orders = dummy_orders()
    balances = dummy_balances()
    conn = connect()
    try:
        # connect() already ran SET TIME ZONE, which opens a transaction.
        # transaction() would only be a savepoint, and close() would roll the run back.
        conn.commit()
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
                INSERT INTO strategy_versions (strategy_id, document, ir, kind)
                VALUES (%s, %s, %s, 'backtest')
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


def _order_row(row: tuple) -> dict[str, Any]:
    return {
        "ts": row[0].isoformat(),
        "symbol": str(row[1]),
        "side": str(row[2]),
        "quantity": float(row[3]),
        "price": float(row[4]),
    }


def _balance_row(row: tuple) -> dict[str, Any]:
    return {"ts": row[0].isoformat(), "cash": float(row[1]), "equity": float(row[2])}


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _closed_trades(orders: list[dict[str, Any]]) -> list[float]:
    """FIFO round trips. A sell against an earlier buy records the cash P&L."""
    lots: dict[str, list[list[float]]] = {}
    closed: list[float] = []
    for order in orders:
        symbol = str(order["symbol"])
        quantity = float(order["quantity"])
        price = float(order["price"])
        book = lots.setdefault(symbol, [])
        if order["side"] == "buy":
            book.append([quantity, price])
            continue
        if order["side"] != "sell":
            continue
        remaining = quantity
        while remaining > 0 and book:
            lot_qty, lot_price = book[0]
            matched = min(remaining, lot_qty)
            closed.append((price - lot_price) * matched)
            remaining -= matched
            leftover = lot_qty - matched
            if leftover <= 1e-9:
                book.pop(0)
            else:
                book[0][0] = leftover
    return closed


def _cagr_pct(balances: list[dict[str, Any]], start: float, end: float) -> float | None:
    if len(balances) < 2 or start <= 0 or end <= 0:
        return None
    opened = _moment(balances[0]["ts"])
    closed = _moment(balances[-1]["ts"])
    if opened is None or closed is None:
        return None
    years = (closed - opened).total_seconds() / (365.25 * 24 * 60 * 60)
    if years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def _sharpe(equities: list[float]) -> float | None:
    """Per-step equity returns, scaled by the square root of the step count. Risk-free rate is 0."""
    returns = [
        (equities[index] - equities[index - 1]) / equities[index - 1]
        for index in range(1, len(equities))
        if equities[index - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    deviation = variance**0.5
    if deviation == 0:
        return None
    return round(mean / deviation * (len(returns) ** 0.5), 2)
