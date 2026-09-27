"""The latest backtest of each strategy a user owns, with headline metrics for portfolio cards."""

from __future__ import annotations

from typing import Any

from mantis import db
from mantis.services import strategies
from mantis.services.backtests import performance


def latest_for_user(user_id: int) -> dict[int, dict[str, Any]]:
    """``{strategy_id: summary}`` for each owned strategy that has at least one backtest."""
    with db.session() as conn:
        runs = conn.execute(
            """
            SELECT DISTINCT ON (v.strategy_id) v.strategy_id, b.id, b.created_at, b.source
            FROM backtests b
            JOIN strategy_versions v ON v.id = b.strategy_version_id
            JOIN strategies s ON s.id = v.strategy_id
            WHERE s.user_id = %s
            ORDER BY v.strategy_id, b.created_at DESC, b.id DESC
            """,
            (user_id,),
        ).fetchall()
        if not runs:
            return {}
        ids = [int(run[1]) for run in runs]
        orders: dict[int, list[dict[str, Any]]] = {backtest_id: [] for backtest_id in ids}
        balances: dict[int, list[dict[str, Any]]] = {backtest_id: [] for backtest_id in ids}
        for backtest_id, ts, symbol, side, quantity, price in conn.execute(
            """
            SELECT backtest_id, ts, symbol, side, quantity, price FROM backtest_orders
            WHERE backtest_id = ANY(%s) ORDER BY backtest_id, ts, id
            """,
            (ids,),
        ):
            orders[int(backtest_id)].append(
                {
                    "ts": ts.isoformat(),
                    "symbol": str(symbol),
                    "side": str(side),
                    "quantity": float(quantity),
                    "price": float(price),
                }
            )
        for backtest_id, ts, cash, equity in conn.execute(
            """
            SELECT backtest_id, ts, cash, equity FROM backtest_balances
            WHERE backtest_id = ANY(%s) ORDER BY backtest_id, ts, id
            """,
            (ids,),
        ):
            balances[int(backtest_id)].append({"ts": ts.isoformat(), "cash": float(cash), "equity": float(equity)})

    summaries: dict[int, dict[str, Any]] = {}
    for strategy_id, backtest_id, created_at, source in runs:
        try:
            metrics = performance(orders[int(backtest_id)], balances[int(backtest_id)])
        except (ArithmeticError, ValueError):
            # One run whose statistics cannot be computed must not break the whole list.
            metrics = {}
        summaries[int(strategy_id)] = {
            "id": int(backtest_id),
            "created_at": created_at.isoformat(),
            "source": source,
            "return_pct": metrics.get("return_pct"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "num_trades": metrics.get("num_trades"),
        }
    return summaries


def list_strategies_with_latest(user_id: int) -> list[dict[str, Any]]:
    """``strategies.list_strategies`` with ``last_backtest`` (or null) on each summary."""
    latest = latest_for_user(user_id)
    return [{**row, "last_backtest": latest.get(row["id"])} for row in strategies.list_strategies(user_id)]
