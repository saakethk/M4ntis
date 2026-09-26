"""Main Backend Server"""

from __future__ import annotations

from typing import Any

import uvicorn
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

import helpers.auth as auth
import helpers.backtests as backtests
import helpers.discussions as discussions
import helpers.strategies as strategies
from helpers.db import env_port
from helpers.symbols import MAX_LIMIT, find_symbol, normalize_symbol_query, search_symbols

BACKEND_PORT = env_port("BACKEND_PORT", 8001)
FRONTEND_PORT = env_port("FRONTEND_PORT", 8002)


def frontend_origins(frontend_port: int) -> list[str]:
    origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    for host in ("0.0.0.0", "localhost", "127.0.0.1"):
        origins.append(f"http://{host}:{frontend_port}")
    return origins


# Vite may bind a port other than FRONTEND_PORT, and the page may be opened
# as http or https on localhost, 127.0.0.1, or 0.0.0.0. Credentials forbid
# allow_origins=["*"]; this regex echoes the request Origin for those hosts
# on any port. Non-local origins stay rejected.
LOCAL_ORIGIN_REGEX = r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?"


app = FastAPI(title="Mantis Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins(FRONTEND_PORT),
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


class Credentials(BaseModel):
    email: str
    password: str


class StrategyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    document: dict[str, Any]
    ir: dict[str, Any] | None = None
    visibility: str | None = None


class BacktestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int
    strategy_id: int


class StrategyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    document: dict[str, Any] | None = None
    ir: dict[str, Any] | None = None
    visibility: str | None = None


class DiscussionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str
    strategy_id: int | None = None
    parent_id: int | None = None


def _require_user(request: Request) -> auth.User:
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    try:
        user = auth.user_from_token(token)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="User database is unavailable") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def _set_session_cookie(response: Response, token: str) -> None:
    # Host-only (no Domain). The browser stores this for the host it called.
    # SameSite=Lax is sent on same-site requests, which is how the Vite dev
    # proxy keeps login and /auth/me together. Secure stays off so plain HTTP
    # local dev can store the cookie. SameSite=None would require Secure.
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


@app.post("/strategies", status_code=201)
def create_strategy_route(body: StrategyCreate, request: Request) -> dict:
    user = _require_user(request)
    try:
        visibility: Any = strategies.PRIVATE
        if "visibility" in body.model_fields_set:
            visibility = strategies.normalize_visibility(body.visibility)
        return strategies.create_strategy(
            user.id, body.name, body.document, body.ir, visibility
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Strategy database is unavailable") from exc


@app.get("/strategies")
def list_strategies_route(request: Request) -> list:
    user = _require_user(request)
    try:
        return strategies.list_strategies(user.id)
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Strategy database is unavailable") from exc


@app.get("/strategies/{strategy_id}")
def get_strategy_route(strategy_id: int, request: Request) -> dict:
    user = _require_user(request)
    try:
        return strategies.get_strategy(user.id, strategy_id)
    except strategies.StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Strategy database is unavailable") from exc


@app.put("/strategies/{strategy_id}")
def update_strategy_route(strategy_id: int, body: StrategyUpdate, request: Request) -> dict:
    user = _require_user(request)
    try:
        visibility: Any = strategies.UNSET
        if "visibility" in body.model_fields_set:
            visibility = strategies.normalize_visibility(body.visibility)
        return strategies.update_strategy(
            user.id,
            strategy_id,
            name=body.name if "name" in body.model_fields_set else strategies.UNSET,
            document=body.document if "document" in body.model_fields_set else strategies.UNSET,
            ir=body.ir if "ir" in body.model_fields_set else strategies.UNSET,
            visibility=visibility,
        )
    except strategies.StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc
    except strategies.StrategyForbidden as exc:
        raise HTTPException(
            status_code=403, detail="Only the owner can change this strategy"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Strategy database is unavailable") from exc


@app.post("/strategies/{strategy_id}/copy", status_code=201)
def copy_strategy_route(strategy_id: int, request: Request) -> dict:
    user = _require_user(request)
    try:
        new_id = strategies.copy_strategy(user.id, strategy_id)
    except strategies.StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Strategy database is unavailable") from exc
    return {"id": new_id}


@app.post("/backtests", status_code=201)
def create_backtest_route(body: BacktestCreate, request: Request) -> dict:
    user = _require_user(request)
    if body.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only run a backtest as yourself")
    try:
        return backtests.run_dummy_backtest(body.user_id, body.strategy_id)
    except backtests.UserNotFound as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except strategies.StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Backtest database is unavailable") from exc


@app.post("/discussions", status_code=201)
def create_discussion_route(body: DiscussionCreate, request: Request) -> dict:
    user = _require_user(request)
    try:
        return discussions.create_post(
            user.id,
            body.body,
            strategy_id=body.strategy_id,
            parent_id=body.parent_id,
        )
    except strategies.StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc
    except strategies.StrategyForbidden as exc:
        raise HTTPException(
            status_code=403,
            detail="Only the owner can publish a private strategy",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail="Discussion database is unavailable") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=BACKEND_PORT)
