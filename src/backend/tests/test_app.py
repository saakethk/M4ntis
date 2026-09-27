"""HTTP behavior that needs no database: CORS, ports, auth guard, symbol routes, errors."""

from __future__ import annotations

from unittest.mock import patch

from src.backend.mantis.services import auth
import pytest

from src.backend.mantis.api.app import frontend_origins
from src.backend.mantis.config import env_port
from src.backend.mantis.services import symbols
from src.backend.mantis.services.symbols import Instrument

SYMBOLS = [
    Instrument("AAPL", "Apple Inc. Common Stock"),
    Instrument("AMZN", "Amazon.com, Inc. Common Stock"),
    Instrument("GS", "The Goldman Sachs Group, Inc. Common Stock"),
    Instrument("META", "Meta Platforms, Inc. Class A Common Stock"),
    Instrument("MSFT", "Microsoft Corporation Common Stock"),
    Instrument("SPCX", "Space Exploration Technologies Corp. Class A Common Stock"),
]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "query, expected",
    [("A", ["AAPL", "AMZN", "META"]), ("M", ["META", "MSFT", "AMZN"]), ("%aap%", ["AAPL"]), ("apple", ["AAPL"])],
)
def test_symbol_ranking(query, expected):
    assert [i.symbol for i in symbols.match_symbols(SYMBOLS, query, limit=10)] == expected


def test_short_query_does_not_scan_names():
    assert "GS" not in [i.symbol for i in symbols.match_symbols(SYMBOLS, "a", limit=20)]


def test_symbol_routes(client):
    with patch.object(symbols, "list_symbols", return_value=SYMBOLS):
        found = client.get("/symbols", params={"q": "sp", "limit": 5})
        exact = client.get("/symbols/meta")
        missing = client.get("/symbols/ZZZZ")
    assert found.json() == {
        "query": "sp",
        "symbols": [{"symbol": "SPCX", "name": "Space Exploration Technologies Corp. Class A Common Stock"}],
    }
    assert exact.json()["symbol"] == "META"
    assert missing.status_code == 404


def test_unconfigured_database_is_503(client, monkeypatch):
    for name in ("TIGER_DB_PGHOST", "TIGER_DB_PGPASSWORD"):
        monkeypatch.delenv(name, raising=False)
    symbols.clear_symbol_cache()
    response = client.get("/symbols", params={"q": "A"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/strategies", "/discussions", "/llm/models", "/auth/me"])
def test_routes_require_a_session(client, path):
    with patch.object(auth, "user_from_token", return_value=None):
        assert client.get(path).status_code == 401


def test_env_port(monkeypatch):
    monkeypatch.setenv("BACKEND_PORT", "8123")
    monkeypatch.setenv("FRONTEND_PORT", "")
    assert env_port("BACKEND_PORT", 8001) == 8123
    assert env_port("FRONTEND_PORT", 8002) == 8002
    monkeypatch.setenv("BACKEND_PORT", "80abc")
    with pytest.raises(ValueError, match="80abc"):
        env_port("BACKEND_PORT", 8001)


def test_cors_origins_are_local_only():
    origins = frontend_origins(9002)
    assert "http://localhost:9002" in origins and "*" not in origins


@pytest.mark.parametrize("origin", ["http://localhost:8002", "http://0.0.0.0:8002", "http://127.0.0.1:49152", "https://localhost:8443"])
def test_local_origins_pass_preflight(client, origin):
    response = client.options(
        "/auth/login",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost.evil.example"])
def test_remote_origins_fail_preflight(client, origin):
    response = client.options(
        "/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 400


def test_password_hashing_round_trip():
    stored = auth.hash_password("correct-horse")
    assert auth.verify_password("correct-horse", stored)
    assert not auth.verify_password("wrong-horse", stored)
    assert not auth.verify_password("x", "not-a-hash")


def test_backtests_fpga_route_is_not_captured_by_id(client):
    with patch.object(auth, "user_from_token", return_value=auth.User(4, "a@b.com")):
        response = client.get("/backtests/fpga", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert "connected" in response.json()


def test_backtests_range_route_is_not_captured_by_id(client):
    with patch.object(auth, "user_from_token", return_value=auth.User(4, "a@b.com")):
        with patch(
            "src.backend.mantis.api.routes.backtests.backtests.backtest_available_range",
            return_value={"symbols": [], "days": []},
        ):
            response = client.get("/backtests/range?strategy_id=1", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200


def test_backtests_non_integer_id_is_not_found(client):
    with patch.object(auth, "user_from_token", return_value=auth.User(4, "a@b.com")):
        response = client.get("/backtests/abc", headers={"Authorization": "Bearer test"})
    assert response.status_code == 404
