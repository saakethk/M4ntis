"""FastAPI application: CORS, error translation, and the routers."""

from __future__ import annotations

import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.backend.mantis.api.routes import symbols
from src.backend.mantis.api.routes import analysis, assistant, auth, backtests, compile, discussions, strategies
from src.backend.mantis.config import env_port
from src.backend.mantis.errors import MantisError
from src.backend.mantis.services.compiler import CompilationFailed, InvalidCompileBody

log = logging.getLogger(__name__)

# Vite may pick another port, and the page may be opened on localhost, 127.0.0.1,
# or 0.0.0.0 over http or https. Credentialed CORS forbids "*", so this pattern
# echoes any local origin on any port and rejects everything else.
LOCAL_ORIGIN_REGEX = r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?"


def frontend_origins(frontend_port: int) -> list[str]:
    fixed = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]
    return fixed + [f"http://{host}:{frontend_port}" for host in ("0.0.0.0", "localhost", "127.0.0.1")]


def create_app() -> FastAPI:
    app = FastAPI(title="Mantis Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_origins(env_port("FRONTEND_PORT", 8002)),
        allow_origin_regex=LOCAL_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )
    _add_error_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (auth, symbols, strategies, compile, assistant, backtests, analysis, discussions):
        app.include_router(module.router)
    return app


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MantisError)
    def domain_error(_: Request, exc: MantisError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(psycopg.Error)
    def database_error(_: Request, exc: psycopg.Error) -> JSONResponse:
        log.warning("database error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Database is unavailable"})

    @app.exception_handler(CompilationFailed)
    def compile_failed(_: Request, exc: CompilationFailed) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "detail": str(exc), "diagnostics": exc.diagnostics})

    @app.exception_handler(InvalidCompileBody)
    def invalid_compile_body(_: Request, exc: InvalidCompileBody) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors)})
