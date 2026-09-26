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
_cached_symbols: tuple[float, list[str]] | None = None


class SymbolSearchResponse(BaseModel):
    query: str
    symbols: list[str]


class SymbolResponse(BaseModel):
    symbol: str = Field(examples=["AAPL"])


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


def match_symbols(symbols: list[str], query: str, limit: int) -> list[str]:
    """Return symbols that start with the query, then symbols that contain it."""
    needle = normalize_symbol_query(query)
    bounded = max(1, min(limit, MAX_LIMIT))
    if not needle:
        return symbols[:bounded]
    prefix = [symbol for symbol in symbols if symbol.startswith(needle)]
    contains = [
        symbol for symbol in symbols if needle in symbol and not symbol.startswith(needle)
    ]
    return (prefix + contains)[:bounded]


def load_symbols() -> list[str]:
    """Read the distinct symbols present in stock_minute_bars."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT symbol
            FROM stock_minute_bars
            GROUP BY symbol
            ORDER BY symbol
            """
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def list_symbols(*, refresh: bool = False) -> list[str]:
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


def search_symbols(query: str, limit: int = 20) -> list[str]:
    """Search symbols stored in the database."""
    return match_symbols(list_symbols(), query, limit)


def find_symbol(symbol: str) -> str | None:
    """Return the stored symbol when it exists, otherwise None."""
    needle = normalize_symbol_query(symbol)
    if not needle:
        return None
    for stored in list_symbols():
        if stored == needle:
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
    return SymbolSearchResponse(query=normalize_symbol_query(q), symbols=symbols)


@app.get("/symbols/{symbol}", response_model=SymbolResponse)
def get_symbol(symbol: str) -> SymbolResponse:
    try:
        stored = find_symbol(symbol)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Symbol database is unavailable") from exc
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Symbol {normalize_symbol_query(symbol) or symbol!r} was not found")
    return SymbolResponse(symbol=stored)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
