"""Checks for the symbol-to-name mapping. No database connection."""

from __future__ import annotations

import unittest
from pathlib import Path

from load_stock_symbols import names_from_nasdaq_payload, read_name_file

DATABASE_DIR = Path(__file__).resolve().parent


class NameFileTest(unittest.TestCase):
    def test_tracked_symbols_have_names(self) -> None:
        names = read_name_file(DATABASE_DIR / "symbols" / "names.csv")
        tracked: list[str] = []
        for filename in ("nasdaq.txt", "sponsors.txt"):
            for line in (DATABASE_DIR / "symbols" / filename).read_text().splitlines():
                symbol = line.strip()
                if symbol:
                    tracked.append(symbol)
        missing = [symbol for symbol in tracked if symbol not in names]
        self.assertEqual(missing, [])
        self.assertEqual(names["AAPL"], "Apple Inc. Common Stock")
        self.assertIn("Visa", names["V"])
        self.assertIn("Goldman", names["GS"])

    def test_nasdaq_payload_parser(self) -> None:
        names = names_from_nasdaq_payload(
            {
                "data": {
                    "data": {
                        "rows": [
                            {"symbol": "aapl", "companyName": "Apple Inc.  Common Stock"},
                            {"symbol": "", "companyName": "Skipped"},
                        ]
                    }
                }
            }
        )
        self.assertEqual(names, {"AAPL": "Apple Inc. Common Stock"})


if __name__ == "__main__":
    unittest.main()
