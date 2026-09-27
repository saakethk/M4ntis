"""Ticker search: ``GET /symbols?q=&limit=`` and ``GET /symbols/{symbol}``."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.mantis.errors import NotFound
from backend.mantis.services import symbols

router = APIRouter(prefix="/symbols", tags=["symbols"])


@router.get("")
def search(q: str = Query(""), limit: int = Query(20, ge=1, le=symbols.MAX_LIMIT)) -> dict:
    return {"query": q.strip(), "symbols": [item.to_api() for item in symbols.search_symbols(q, limit)]}


@router.get("/{symbol}")
def lookup(symbol: str) -> dict:
    found = symbols.find_symbol(symbol)
    if found is None:
        raise NotFound(f"Symbol {symbols.normalize_symbol_query(symbol) or symbol} was not found")
    return found.to_api()
