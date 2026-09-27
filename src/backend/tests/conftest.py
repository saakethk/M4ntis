"""Shared fixtures.

Database tests need a disposable PostgreSQL database named by ``MANTIS_TEST_DATABASE``,
e.g. ``postgresql://mantis:mantis@127.0.0.1:5432/mantis_test``. They are skipped
when it is unset. Every test that uses ``database`` starts from empty tables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.backend.mantis.api.app import create_app  # noqa: E402
from src.backend.mantis.blocks.canvas import normalize_graph  # noqa: E402
from src.backend.mantis.blocks.document import document_from_canvas  # noqa: E402
from src.backend.mantis.config import COMPILER_ROOT  # noqa: E402
from src.backend.mantis.db import schema  # noqa: E402

sys.path.insert(0, str(COMPILER_ROOT))

# Buys while the 3-tick SMA of AAPL is above the 10-tick SMA and sells otherwise.
CROSSOVER = document_from_canvas(
    normalize_graph(
        {
            "nodes": [
                {"id": "start", "type": "start", "params": {"resolution": "1m", "startingBalance": 10000}},
                {"id": "t0", "type": "get_ticker", "params": {"symbol": "AAPL"}},
                {"id": "fast", "type": "sma", "params": {"n": 3}},
                {"id": "slow", "type": "sma", "params": {"n": 10}},
                {"id": "cross", "type": "if", "params": {"operator": ">"}},
                {"id": "buy", "type": "buy", "params": {"quantity": 1}},
                {"id": "sell", "type": "sell", "params": {"quantity": 1}},
            ],
            "edges": [
                {"source": "start", "sourceHandle": "exec:out", "target": "cross", "targetHandle": "exec:in"},
                {"source": "fast", "sourceHandle": "data:out", "target": "cross", "targetHandle": "data:a"},
                {"source": "slow", "sourceHandle": "data:out", "target": "cross", "targetHandle": "data:b"},
                {"source": "cross", "sourceHandle": "exec:then", "target": "buy", "targetHandle": "exec:in"},
                {"source": "cross", "sourceHandle": "exec:else", "target": "sell", "targetHandle": "exec:in"},
            ],
        }
    ),
    name="Crossover",
)

TABLES = (
    "backtest_balances",
    "backtest_orders",
    "backtests",
    "discussion_likes",
    "discussion_posts",
    "strategy_versions",
    "strategies",
    "sessions",
    "users",
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("MANTIS_TEST_DATABASE")
    if not url:
        pytest.skip("MANTIS_TEST_DATABASE is not set")
    parsed = urlparse(url)
    settings = {
        "TIGER_DB_PGHOST": parsed.hostname or "127.0.0.1",
        "TIGER_DB_PGPORT": str(parsed.port or 5432),
        "TIGER_DB_PGDATABASE": parsed.path.lstrip("/"),
        "TIGER_DB_PGUSER": parsed.username or "",
        "TIGER_DB_PGPASSWORD": parsed.password or "",
        "TIGER_DB_PGSSLMODE": "disable",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE")
    schema.reset_for_tests()
    yield url
    schema.reset_for_tests()


def sign_up(client: TestClient, email: str) -> dict:
    response = client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    assert response.status_code == 201, response.text
    return response.json()
