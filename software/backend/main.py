"""Main Backend Server"""

from __future__ import annotations

import uvicorn
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import helpers.auth as auth
from helpers.symbols import MAX_LIMIT, find_symbol, normalize_symbol_query, search_symbols

app = FastAPI(title="Ticker search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Credentials(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=auth.SESSION_DAYS * 24 * 60 * 60,
        path="/",
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


@app.post("/auth/register", status_code=201)
def register(body: Credentials, response: Response) -> dict:
    try:
        user, token = auth.register_user(body.email, body.password)
    except auth.EmailTaken as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="User database is unavailable") from exc
    _set_session_cookie(response, token)
    return {"id": user.id, "email": user.email}


@app.post("/auth/login")
def login(body: Credentials, response: Response) -> dict:
    try:
        user, token = auth.login(body.email, body.password)
    except auth.InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="User database is unavailable") from exc
    _set_session_cookie(response, token)
    return {"id": user.id, "email": user.email}


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    try:
        auth.logout(token)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="User database is unavailable") from exc
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/auth/me")
def me(request: Request) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    try:
        user = auth.user_from_token(token)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="User database is unavailable") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return {"id": user.id, "email": user.email}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
