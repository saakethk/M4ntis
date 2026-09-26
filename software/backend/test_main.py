"""Tests for symbol search that do not require Tiger Data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import symbols
from symbols import Instrument

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


if __name__ == "__main__":
    unittest.main()
