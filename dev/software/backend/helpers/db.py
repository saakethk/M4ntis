"""Tiger Data connection shared by the backend."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

_REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)


def _repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def load_repo_env() -> None:
    """Load the repo-root .env. Values already set in the process are kept."""
    load_dotenv(_repo_root() / ".env")


def env_port(name: str, default: int) -> int:
    """Listen port from the repo-root env. Empty uses default; a non-integer fails."""
    load_repo_env()
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip()
    if not text.isascii() or not text.isdigit():
        raise ValueError(f"{name} must be an integer from 1 to 65535, got {raw!r}")
    port = int(text)
    if port < 1 or port > 65535:
        raise ValueError(f"{name} must be an integer from 1 to 65535, got {raw!r}")
    return port


def connect() -> psycopg.Connection:
    load_repo_env()
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
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
