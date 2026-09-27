"""Ticker and company-name search over the stocks stored in Tiger Data.

The symbol list is small (NASDAQ-100), so it is loaded once, cached for a few
minutes, and ranked in memory.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from backend.mantis import db

MAX_LIMIT = 100
CACHE_SECONDS = 300

_cache_lock = threading.Lock()
_cached: tuple[float, list["Instrument"]] | None = None


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str

    def to_api(self) -> dict[str, str]:
        return {"symbol": self.symbol, "name": self.name}


def normalize_symbol_query(query: str) -> str:
    """Keep letters, digits, dots, and dashes so the query cannot act as a wildcard."""
    return "".join(ch for ch in query.strip().upper() if ch.isalnum() or ch in ".-")


def match_symbols(symbols: list[Instrument], query: str, limit: int) -> list[Instrument]:
    """Rank exact, prefix, and substring ticker matches ahead of company-name matches.

    Queries shorter than three characters match tickers only, so "a" does not match
    every company with an "a" in its name.
    """
    symbol_needle = normalize_symbol_query(query)
    name_needle = " ".join(query.strip().casefold().split())
    bounded = max(1, min(limit, MAX_LIMIT))
    if not symbol_needle and not name_needle:
        return symbols[:bounded]
    ranked = [
        (rank, item)
        for item in symbols
        if (rank := _rank(item, symbol_needle, name_needle)) is not None
    ]
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked[:bounded]]


def search_symbols(query: str, limit: int = 20) -> list[Instrument]:
    return match_symbols(list_symbols(), query, limit)


def find_symbol(symbol: str) -> Instrument | None:
    needle = normalize_symbol_query(symbol)
    if not needle:
        return None
    return next((item for item in list_symbols() if item.symbol == needle), None)


def list_symbols(*, refresh: bool = False) -> list[Instrument]:
    global _cached
    with _cache_lock:
        if not refresh and _cached is not None and time.monotonic() - _cached[0] < CACHE_SECONDS:
            return _cached[1]
    symbols = _load_symbols()
    with _cache_lock:
        _cached = (time.monotonic(), symbols)
    return symbols


def clear_symbol_cache() -> None:
    global _cached
    with _cache_lock:
        _cached = None


def _rank(item: Instrument, symbol_needle: str, name_needle: str) -> int | None:
    if symbol_needle:
        if item.symbol == symbol_needle:
            return 0
        if item.symbol.startswith(symbol_needle):
            return 1
        if symbol_needle in item.symbol:
            return 2
    if len(name_needle) >= 3:
        name = item.name.casefold()
        if name.startswith(name_needle):
            return 3
        if name_needle in name:
            return 4
    return None


def _load_symbols() -> list[Instrument]:
    """Named symbols, plus tickers that have bars but no name yet (named after themselves)."""
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT symbol, name FROM stock_symbols
            UNION
            SELECT symbol, symbol FROM stock_minute_bars
            WHERE NOT EXISTS (
                SELECT 1 FROM stock_symbols WHERE stock_symbols.symbol = stock_minute_bars.symbol
            )
            ORDER BY symbol
            """
        ).fetchall()
    return [Instrument(str(row[0]), str(row[1])) for row in rows]
