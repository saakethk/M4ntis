"""FastAPI server for searching stock symbols stored in Tiger Data.

Run from the repository root:

    python software/backend/main.py
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)
SYMBOL_CACHE_SECONDS = 300
MAX_LIMIT = 100

app = FastAPI(title="Ticker search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_cache_lock = threading.Lock()
_cached_symbols: tuple[float, list["Instrument"]] | None = None


class Instrument(BaseModel):
    symbol: str
    name: str


class SymbolSearchResponse(BaseModel):
    query: str
    symbols: list[Instrument]


class SymbolResponse(Instrument):
    symbol: str = Field(examples=["AAPL"])
    name: str = Field(examples=["Apple Inc. Common Stock"])


def _find_repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def _connect() -> psycopg.Connection:
    load_dotenv(_find_repo_root() / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    conn = psycopg.connect(
        host=os.environ["TIGER_DB_PGHOST"],
        port=os.environ["TIGER_DB_PGPORT"],
        dbname=os.environ["TIGER_DB_PGDATABASE"],
        user=os.environ["TIGER_DB_PGUSER"],
        password=os.environ["TIGER_DB_PGPASSWORD"],
        sslmode=os.environ.get("TIGER_DB_PGSSLMODE", "require"),
    )
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


def normalize_symbol_query(query: str) -> str:
    """Keep letters, digits, dots, and dashes so LIKE wildcards cannot be injected."""
    return "".join(
        character for character in query.strip().upper() if character.isalnum() or character in ".-"
    )


def normalize_name_query(query: str) -> str:
    """Collapse whitespace and case so a company name can be matched."""
    return " ".join(query.strip().casefold().split())


def match_symbols(symbols: list[Instrument], query: str, limit: int) -> list[Instrument]:
    """Rank symbol matches ahead of company-name matches.

    A query shorter than three characters searches tickers only. Longer
    queries also match the company name from stock_symbols.
    """
    symbol_needle = normalize_symbol_query(query)
    name_needle = normalize_name_query(query)
    bounded = max(1, min(limit, MAX_LIMIT))
    if not symbol_needle and not name_needle:
        return symbols[:bounded]

    exact: list[Instrument] = []
    prefix: list[Instrument] = []
    contains: list[Instrument] = []
    name_prefix: list[Instrument] = []
    name_contains: list[Instrument] = []
    search_names = len(name_needle) >= 3
    for item in symbols:
        symbol = item.symbol
        name = item.name.casefold()
        if symbol_needle and symbol == symbol_needle:
            exact.append(item)
        elif symbol_needle and symbol.startswith(symbol_needle):
            prefix.append(item)
        elif symbol_needle and symbol_needle in symbol:
            contains.append(item)
        elif search_names and name.startswith(name_needle):
            name_prefix.append(item)
        elif search_names and name_needle in name:
            name_contains.append(item)
    return (exact + prefix + contains + name_prefix + name_contains)[:bounded]


def load_symbols() -> list[Instrument]:
    """Read symbols from stock_symbols, including bar tickers that have no name yet."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT symbol, name
            FROM stock_symbols
            UNION
            SELECT bars.symbol, bars.symbol
            FROM (
                SELECT symbol
                FROM stock_minute_bars
                GROUP BY symbol
            ) AS bars
            WHERE NOT EXISTS (
                SELECT 1
                FROM stock_symbols
                WHERE stock_symbols.symbol = bars.symbol
            )
            ORDER BY symbol
            """
        ).fetchall()
    finally:
        conn.close()
    return [Instrument(symbol=str(row[0]), name=str(row[1])) for row in rows]


def list_symbols(*, refresh: bool = False) -> list[Instrument]:
    """Return cached symbols, reloading from Tiger Data when the cache is stale."""
    global _cached_symbols
    now = time.monotonic()
    with _cache_lock:
        if (
            not refresh
            and _cached_symbols is not None
            and now - _cached_symbols[0] < SYMBOL_CACHE_SECONDS
        ):
            return _cached_symbols[1]
    symbols = load_symbols()
    with _cache_lock:
        _cached_symbols = (time.monotonic(), symbols)
    return symbols


def search_symbols(query: str, limit: int = 20) -> list[Instrument]:
    """Search symbols and company names stored in the database."""
    return match_symbols(list_symbols(), query, limit)


def find_symbol(symbol: str) -> Instrument | None:
    """Return the stored symbol when it exists, otherwise None."""
    needle = normalize_symbol_query(symbol)
    if not needle:
        return None
    for stored in list_symbols():
        if stored.symbol == needle:
            return stored
    return None


def clear_symbol_cache() -> None:
    global _cached_symbols
    with _cache_lock:
        _cached_symbols = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/symbols", response_model=SymbolSearchResponse)
def search_symbols_route(
    q: str = Query("", description="Symbol text to search for"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
) -> SymbolSearchResponse:
    try:
        symbols = search_symbols(q, limit)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Symbol database is unavailable") from exc
    return SymbolSearchResponse(query=q.strip(), symbols=symbols)


@app.get("/symbols/{symbol}", response_model=SymbolResponse)
def get_symbol(symbol: str) -> SymbolResponse:
    try:
        stored = find_symbol(symbol)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Symbol database is unavailable") from exc
    if stored is None:
        label = normalize_symbol_query(symbol) or symbol
        raise HTTPException(status_code=404, detail=f"Symbol {label} was not found")
    return SymbolResponse(symbol=stored.symbol, name=stored.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
