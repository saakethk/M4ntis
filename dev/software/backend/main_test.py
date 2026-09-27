"""Tests for symbol search that do not require Tiger Data."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import dev.software.backend.main as main
import dev.software.backend.helpers.symbols as symbols
from dev.software.backend.helpers.db import env_port
from dev.software.backend.helpers.symbols import Instrument

SYMBOLS = [
    Instrument("AAPL", "Apple Inc. Common Stock"),
    Instrument("AMZN", "Amazon.com, Inc. Common Stock"),
    Instrument("GS", "The Goldman Sachs Group, Inc. Common Stock"),
    Instrument("META", "Meta Platforms, Inc. Class A Common Stock"),
    Instrument("MSFT", "Microsoft Corporation Common Stock"),
    Instrument("SPCX", "Space Exploration Technologies Corp. Class A Common Stock"),
    Instrument("V", "Visa Inc. Common Stock"),
]


class MatchSymbolsTest(unittest.TestCase):
    def test_prefix_matches_rank_ahead_of_contains(self) -> None:
        matches = symbols.match_symbols(SYMBOLS, "A", limit=10)
        self.assertEqual([item.symbol for item in matches], ["AAPL", "AMZN", "META"])

    def test_contains_match_follows_prefix(self) -> None:
        matches = symbols.match_symbols(SYMBOLS, "M", limit=10)
        self.assertEqual([item.symbol for item in matches], ["META", "MSFT", "AMZN"])

    def test_empty_query_returns_the_first_symbols(self) -> None:
        self.assertEqual(
            [item.symbol for item in symbols.match_symbols(SYMBOLS, "  ", limit=2)],
            ["AAPL", "AMZN"],
        )

    def test_wildcard_characters_are_removed(self) -> None:
        self.assertEqual(symbols.normalize_symbol_query("%a_"), "A")
        self.assertEqual(
            [item.symbol for item in symbols.match_symbols(SYMBOLS, "%aap%", limit=5)],
            ["AAPL"],
        )

    def test_company_name_match(self) -> None:
        matches = symbols.match_symbols(SYMBOLS, "apple", limit=5)
        self.assertEqual([item.symbol for item in matches], ["AAPL"])

    def test_short_query_does_not_scan_names(self) -> None:
        matches = symbols.match_symbols(SYMBOLS, "a", limit=20)
        self.assertNotIn("GS", [item.symbol for item in matches])


class SymbolRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        symbols.clear_symbol_cache()
        self.client = TestClient(main.app)

    def test_search_route(self) -> None:
        with patch.object(symbols, "list_symbols", return_value=SYMBOLS):
            response = self.client.get("/symbols", params={"q": "sp", "limit": 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "query": "sp",
                "symbols": [
                    {
                        "symbol": "SPCX",
                        "name": "Space Exploration Technologies Corp. Class A Common Stock",
                    }
                ],
            },
        )

    def test_exact_symbol_route(self) -> None:
        with patch.object(symbols, "list_symbols", return_value=SYMBOLS):
            found = self.client.get("/symbols/meta")
            missing = self.client.get("/symbols/ZZZZ")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(
            found.json(),
            {"symbol": "META", "name": "Meta Platforms, Inc. Class A Common Stock"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_database_outage_is_a_service_error(self) -> None:
        with patch.object(symbols, "list_symbols", side_effect=RuntimeError("missing env")):
            response = self.client.get("/symbols", params={"q": "A"})
        self.assertEqual(response.status_code, 503)


class EnvPortTest(unittest.TestCase):
    def test_repo_env_file_sets_backend_port_and_blank_frontend_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("BACKEND_PORT=8123\nFRONTEND_PORT=\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("BACKEND_PORT", None)
                os.environ.pop("FRONTEND_PORT", None)
                with patch("helpers.db._repo_root", return_value=root):
                    self.assertEqual(env_port("BACKEND_PORT", 8001), 8123)
                    self.assertEqual(env_port("FRONTEND_PORT", 8002), 8002)

    def test_process_environment_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("BACKEND_PORT=1111\n", encoding="utf-8")
            with patch.dict(os.environ, {"BACKEND_PORT": "2222"}, clear=True):
                with patch("helpers.db._repo_root", return_value=root):
                    self.assertEqual(env_port("BACKEND_PORT", 8001), 2222)

    def test_non_integer_port_fails(self) -> None:
        with patch.dict(os.environ, {"BACKEND_PORT": "80abc"}, clear=True):
            with patch("helpers.db.load_dotenv"):
                with self.assertRaises(ValueError) as caught:
                    env_port("BACKEND_PORT", 8001)
        self.assertIn("BACKEND_PORT", str(caught.exception))
        self.assertIn("80abc", str(caught.exception))

    def test_cors_allows_configured_frontend_port_and_dev_origins(self) -> None:
        origins = main.frontend_origins(9002)
        self.assertEqual(
            origins,
            [
                "http://localhost:3000",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:5173",
                "http://0.0.0.0:9002",
                "http://localhost:9002",
                "http://127.0.0.1:9002",
            ],
        )
        self.assertNotIn("*", origins)


class LoginCorsPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def _preflight(self, origin: str):
        return self.client.options(
            "/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

    def test_local_dev_origins_pass_login_preflight(self) -> None:
        origins = [
            "http://localhost:8002",
            "http://0.0.0.0:8002",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:49152",
            "https://localhost:8443",
        ]
        for origin in origins:
            with self.subTest(origin=origin):
                response = self._preflight(origin)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertEqual(response.headers["access-control-allow-credentials"], "true")
                allow_headers = response.headers["access-control-allow-headers"].lower()
                self.assertIn("content-type", allow_headers)
                allow_methods = response.headers["access-control-allow-methods"]
                for method in ("GET", "POST", "PUT"):
                    self.assertIn(method, allow_methods)

    def test_non_local_origin_is_rejected(self) -> None:
        for origin in ("https://evil.example", "http://localhost.evil.example"):
            with self.subTest(origin=origin):
                response = self._preflight(origin)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("Disallowed CORS origin", response.text)
                self.assertNotEqual(response.headers.get("access-control-allow-origin"), origin)


if __name__ == "__main__":
    unittest.main()
