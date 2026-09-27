"""Backtest runs and the performance metrics derived from them.

Runs are currently *sample* runs: nothing is simulated against market data yet.
A run snapshots the strategy as it is now (a ``backtest`` strategy version), then
stores a fixed set of orders and balances. Everything downstream (storage, the
report endpoint, metrics, and the UI) is real, so swapping :func:`sample_orders`
and :func:`sample_balances` for a simulator is the only change a real backtester needs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from mantis import db
from mantis.errors import Forbidden, NotFound
from mantis.services import strategies

SAMPLE_START = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def sample_orders() -> list[dict[str, Any]]:
    return [
        {"ts": SAMPLE_START, "symbol": "AAPL", "side": "buy", "quantity": 10, "price": 180.0},
        {"ts": SAMPLE_START + timedelta(days=1), "symbol": "AAPL", "side": "sell", "quantity": 10, "price": 186.0},
    ]


def sample_balances() -> list[dict[str, Any]]:
    return [
        {"ts": SAMPLE_START, "cash": 100_000.0, "equity": 100_000.0},
        {"ts": SAMPLE_START + timedelta(minutes=1), "cash": 98_200.0, "equity": 100_000.0},
        {"ts": SAMPLE_START + timedelta(days=1), "cash": 100_060.0, "equity": 100_060.0},
    ]


def sample_menu() -> dict[str, Any]:
    """The sample series without storing a run."""
    orders = [_iso(order) for order in sample_orders()]
    balances = [_iso(point) for point in sample_balances()]
    metrics = performance(orders, balances)
    return {
        "dummy": True,
        "equity": metrics["equity"],
        "return_pct": metrics["return_pct"],
        "orders": orders,
        "balances": balances,
    }


def run_backtest(user_id: int, requested_user_id: int, strategy_id: int) -> dict[str, Any]:
    """Record a sample run of a strategy the user can view."""
    if requested_user_id != user_id:
        raise Forbidden("You can only run a backtest as yourself")
    orders = sample_orders()
    balances = sample_balances()
    with db.session() as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is None:
            raise NotFound("User not found")
        strategy = strategies.load_viewable(conn, user_id, strategy_id)
        version_id = int(
            conn.execute(
                """
                INSERT INTO strategy_versions (strategy_id, document, ir, kind)
                VALUES (%s, %s, %s, 'backtest') RETURNING id
                """,
                (
                    strategy_id,
                    Jsonb(strategy.document),
                    Jsonb(strategy.ir) if strategy.ir is not None else None,
                ),
            ).fetchone()[0]
        )
        backtest_id = int(
            conn.execute(
                "INSERT INTO backtests (strategy_version_id, user_id) VALUES (%s, %s) RETURNING id",
                (version_id, user_id),
            ).fetchone()[0]
        )
        conn.cursor().executemany(
            """
            INSERT INTO backtest_orders (backtest_id, ts, symbol, side, quantity, price)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (backtest_id, o["ts"], o["symbol"], o["side"], o["quantity"], o["price"])
                for o in orders
            ],
        )
        conn.cursor().executemany(
            "INSERT INTO backtest_balances (backtest_id, ts, cash, equity) VALUES (%s, %s, %s, %s)",
            [(backtest_id, b["ts"], b["cash"], b["equity"]) for b in balances],
        )
    return {
        "id": backtest_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "strategy_version_id": version_id,
        "dummy": True,
        "orders": [_iso(order) for order in orders],
        "balances": [_iso(point) for point in balances],
    }


def get_backtest(viewer_id: int, backtest_id: int) -> dict[str, Any]:
    """A stored run for its runner, or for anyone who can view the strategy."""
    with db.session() as conn:
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
        runner_id = None if row is None else int(row[1])
        if row is None or (
            runner_id != viewer_id and not strategies.can_view(int(row[6]), str(row[7]), viewer_id)
        ):
            raise NotFound("Backtest not found")
        order_rows = conn.execute(
            "SELECT ts, symbol, side, quantity, price FROM backtest_orders WHERE backtest_id = %s ORDER BY ts, id",
            (backtest_id,),
        ).fetchall()
        balance_rows = conn.execute(
            "SELECT ts, cash, equity FROM backtest_balances WHERE backtest_id = %s ORDER BY ts, id",
            (backtest_id,),
        ).fetchall()
    orders = [
        {"ts": r[0].isoformat(), "symbol": str(r[1]), "side": str(r[2]), "quantity": float(r[3]), "price": float(r[4])}
        for r in order_rows
    ]
    balances = [{"ts": r[0].isoformat(), "cash": float(r[1]), "equity": float(r[2])} for r in balance_rows]
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


def performance(orders: list[dict[str, Any]], balances: list[dict[str, Any]]) -> dict[str, Any]:
    """Return, drawdown, CAGR, Sharpe, and per-trade statistics from orders and the equity path."""
    equities = [float(point["equity"]) for point in balances]
    start = equities[0] if equities else 0.0
    end = equities[-1] if equities else 0.0
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
        "return_pct": round(0.0 if start == 0 else (end - start) / start * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "gross_pnl": round(end - start, 2),
        "cagr_pct": _cagr_pct(balances, start, end),
        "sharpe": _sharpe(equities),
        "num_trades": len(closed),
        "num_trades_won": len(wins),
        "num_trades_lost": len(losses),
        "avg_win_amount": _mean(wins),
        "avg_loss_amount": _mean(losses),
        "expected_pnl_per_trade": _mean(closed),
        "trade_returns": [round(pnl, 2) for pnl in closed],
    }


def _closed_trades(orders: list[dict[str, Any]]) -> list[float]:
    """Cash P&L of each FIFO round trip: a sell closes the oldest open buys first."""
    lots: dict[str, list[list[float]]] = {}
    closed: list[float] = []
    for order in orders:
        book = lots.setdefault(str(order["symbol"]), [])
        quantity, price = float(order["quantity"]), float(order["price"])
        if order["side"] == "buy":
            book.append([quantity, price])
            continue
        if order["side"] != "sell":
            continue
        remaining = quantity
        while remaining > 0 and book:
            lot_quantity, lot_price = book[0]
            matched = min(remaining, lot_quantity)
            closed.append((price - lot_price) * matched)
            remaining -= matched
            if lot_quantity - matched <= 1e-9:
                book.pop(0)
            else:
                book[0][0] = lot_quantity - matched
    return closed


def _cagr_pct(balances: list[dict[str, Any]], start: float, end: float) -> float | None:
    if len(balances) < 2 or start <= 0 or end <= 0:
        return None
    opened, closed = _moment(balances[0]["ts"]), _moment(balances[-1]["ts"])
    years = (closed - opened).total_seconds() / (365.25 * 24 * 60 * 60)
    if years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def _sharpe(equities: list[float]) -> float | None:
    """Mean over standard deviation of per-step returns, scaled by sqrt(steps). Risk-free rate 0."""
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    deviation = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
    if deviation == 0:
        return None
    return round(mean / deviation * len(returns) ** 0.5, 2)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _moment(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "ts": row["ts"].isoformat()}
