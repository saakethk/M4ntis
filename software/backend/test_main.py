"""Tests for symbol search that do not require Tiger Data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


SYMBOLS = ["AAPL", "AMZN", "META", "MSFT", "SPCX", "V"]


class MatchSymbolsTest(unittest.TestCase):
    def test_prefix_matches_rank_ahead_of_contains(self) -> None:
        matches = main.match_symbols(["AAPL", "META", "V", "AVGO"], "A", limit=10)
        self.assertEqual(matches, ["AAPL", "AVGO", "META"])

    def test_contains_match_follows_prefix(self) -> None:
        matches = main.match_symbols(["AAPL", "META", "TMUS"], "M", limit=10)
        self.assertEqual(matches, ["META", "TMUS"])

    def test_empty_query_returns_the_first_symbols(self) -> None:
        self.assertEqual(main.match_symbols(SYMBOLS, "  ", limit=2), ["AAPL", "AMZN"])

    def test_wildcard_characters_are_removed(self) -> None:
        self.assertEqual(main.normalize_symbol_query("%a_"), "A")
        self.assertEqual(
            main.match_symbols(SYMBOLS, "%aap%", limit=5),
            ["AAPL"],
        )


class SymbolRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        main.clear_symbol_cache()
        self.client = TestClient(main.app)

    def test_search_route(self) -> None:
        with patch.object(main, "list_symbols", return_value=SYMBOLS):
            response = self.client.get("/symbols", params={"q": "sp", "limit": 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"query": "SP", "symbols": ["SPCX"]})

    def test_exact_symbol_route(self) -> None:
        with patch.object(main, "list_symbols", return_value=SYMBOLS):
            found = self.client.get("/symbols/meta")
            missing = self.client.get("/symbols/ZZZZ")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json(), {"symbol": "META"})
        self.assertEqual(missing.status_code, 404)

    def test_database_outage_is_a_service_error(self) -> None:
        with patch.object(main, "list_symbols", side_effect=RuntimeError("missing env")):
            response = self.client.get("/symbols", params={"q": "A"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
