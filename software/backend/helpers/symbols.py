"""Search tickers and company names stored in Tiger Data."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from helpers.db import connect

MAX_LIMIT = 100
_CACHE_SECONDS = 300
_cache_lock = threading.Lock()
_cached: tuple[float, list["Instrument"]] | None = None


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str


def normalize_symbol_query(query: str) -> str:
    """Keep letters, digits, dots, and dashes so the query cannot act as a wildcard."""
    return "".join(
        character
        for character in query.strip().upper()
        if character.isalnum() or character in ".-"
    )


def match_symbols(symbols: list[Instrument], query: str, limit: int) -> list[Instrument]:
    """Rank exact and prefix tickers ahead of company-name matches.

    Queries shorter than three characters match tickers only.
    """
    symbol_needle = normalize_symbol_query(query)
    name_needle = " ".join(query.strip().casefold().split())
    bounded = max(1, min(limit, MAX_LIMIT))
    if not symbol_needle and not name_needle:
        return symbols[:bounded]

    ranked: list[tuple[int, Instrument]] = []
    for item in symbols:
        rank = _rank(item, symbol_needle, name_needle)
        if rank is not None:
            ranked.append((rank, item))
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked[:bounded]]


def _rank(item: Instrument, symbol_needle: str, name_needle: str) -> int | None:
    symbol = item.symbol
    if symbol_needle:
        if symbol == symbol_needle:
            return 0
        if symbol.startswith(symbol_needle):
            return 1
        if symbol_needle in symbol:
            return 2
    if len(name_needle) >= 3:
        name = item.name.casefold()
        if name.startswith(name_needle):
            return 3
        if name_needle in name:
            return 4
    return None


def load_symbols() -> list[Instrument]:
    """Read stock_symbols, plus bar tickers that do not have a name yet."""
    conn = connect()
    try:
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
    finally:
        conn.close()
    return [Instrument(str(row[0]), str(row[1])) for row in rows]


def list_symbols(*, refresh: bool = False) -> list[Instrument]:
    global _cached
    now = time.monotonic()
    with _cache_lock:
        if not refresh and _cached is not None and now - _cached[0] < _CACHE_SECONDS:
            return _cached[1]
    symbols = load_symbols()
    with _cache_lock:
        _cached = (time.monotonic(), symbols)
    return symbols


def search_symbols(query: str, limit: int = 20) -> list[Instrument]:
    return match_symbols(list_symbols(), query, limit)


def find_symbol(symbol: str) -> Instrument | None:
    needle = normalize_symbol_query(symbol)
    if not needle:
        return None
    return next((item for item in list_symbols() if item.symbol == needle), None)


def clear_symbol_cache() -> None:
    global _cached
    with _cache_lock:
        _cached = None
