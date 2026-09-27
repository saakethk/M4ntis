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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mantis.api.app import create_app  # noqa: E402
from mantis.db import schema  # noqa: E402

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
