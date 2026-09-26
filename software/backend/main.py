"""HTTP API for symbol search.

Run from the repository root:

    python software/backend/main.py
"""

from __future__ import annotations

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from symbols import MAX_LIMIT, find_symbol, normalize_symbol_query, search_symbols

app = FastAPI(title="Ticker search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/symbols")
def search_symbols_route(
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
) -> dict:
    try:
        symbols = search_symbols(q, limit)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Symbol database is unavailable") from exc
    return {
        "query": q.strip(),
        "symbols": [{"symbol": item.symbol, "name": item.name} for item in symbols],
    }


@app.get("/symbols/{symbol}")
def get_symbol(symbol: str) -> dict:
    try:
        stored = find_symbol(symbol)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Symbol database is unavailable") from exc
    if stored is None:
        label = normalize_symbol_query(symbol) or symbol
        raise HTTPException(status_code=404, detail=f"Symbol {label} was not found")
    return {"symbol": stored.symbol, "name": stored.name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
