"""``GET /strategies`` attaches each strategy's latest backtest with headline metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
from fastapi.testclient import TestClient

from mantis.api.app import create_app
from mantis.blocks.canvas import empty_canvas
from mantis.blocks.document import document_from_canvas
from tests.conftest import sign_up

DOCUMENT = document_from_canvas(empty_canvas(), name="Summary")
T0 = datetime(2026, 3, 2, 14, 30, tzinfo=timezone.utc)


def _insert_run(
    conn: psycopg.Connection,
    strategy_id: int,
    user_id: int,
    created_at: datetime,
    equities: list[float],
    orders: list[tuple[str, float]] = (),
) -> int:
    version_id = conn.execute(
        "SELECT id FROM strategy_versions WHERE strategy_id = %s ORDER BY id LIMIT 1", (strategy_id,)
    ).fetchone()[0]
    backtest_id = conn.execute(
        "INSERT INTO backtests (strategy_version_id, user_id, created_at, source) VALUES (%s, %s, %s, 'fpga') RETURNING id",
        (version_id, user_id, created_at),
    ).fetchone()[0]
    for step, equity in enumerate(equities):
        conn.execute(
            "INSERT INTO backtest_balances (backtest_id, ts, cash, equity) VALUES (%s, %s, %s, %s)",
            (backtest_id, T0 + timedelta(days=step), equity, equity),
        )
    for step, (side, price) in enumerate(orders):
        conn.execute(
            "INSERT INTO backtest_orders (backtest_id, ts, symbol, side, quantity, price) VALUES (%s, %s, 'AAPL', %s, 1, %s)",
            (backtest_id, T0 + timedelta(days=step), side, price),
        )
    return backtest_id


def test_list_strategies_includes_latest_backtest(database):
    owner, other = TestClient(create_app()), TestClient(create_app())
    owner_id = sign_up(owner, "owner@example.com")["id"]
    other_id = sign_up(other, "other@example.com")["id"]
    tested = owner.post("/strategies", json={"name": "Tested", "document": DOCUMENT}).json()["id"]
    untested = owner.post("/strategies", json={"name": "Untested", "document": DOCUMENT}).json()["id"]
    foreign = other.post("/strategies", json={"name": "Foreign", "document": DOCUMENT}).json()["id"]

    with psycopg.connect(database, autocommit=True) as conn:
        _insert_run(conn, tested, owner_id, T0, [10_000, 9_000])
        latest = _insert_run(
            conn,
            tested,
            owner_id,
            T0 + timedelta(hours=1),
            [10_000, 12_000, 9_000, 11_000],
            [("buy", 100), ("sell", 110)],
        )
        _insert_run(conn, foreign, other_id, T0 + timedelta(hours=2), [10_000, 20_000])

    rows = {row["id"]: row for row in owner.get("/strategies").json()}
    assert set(rows) == {tested, untested}
    assert rows[untested]["last_backtest"] is None
    summary = rows[tested]["last_backtest"]
    assert summary["id"] == latest
    assert datetime.fromisoformat(summary["created_at"]) == T0 + timedelta(hours=1)
    assert summary["source"] == "fpga"
    assert summary["return_pct"] == 10.0
    assert summary["max_drawdown_pct"] == 25.0
    assert summary["num_trades"] == 1

    assert other.get("/strategies").json()[0]["last_backtest"]["return_pct"] == 100.0
