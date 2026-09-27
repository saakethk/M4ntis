"""Create discussion and backtest tables.

Run from the repository root after users and strategies exist:

    python software/database/load_users.py
    python software/database/load_strategies.py
    python software/database/load_discussions_backtests.py

The statements use CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS,
so running the loader again leaves the existing rows in place.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SQL_PATH = Path(__file__).resolve().parent / "sql" / "discussions_backtests.sql"
REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)


def find_repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def load_discussions_backtests() -> None:
    load_dotenv(find_repo_root() / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env at the repo root and fill them in."
        )
    conn = psycopg.connect(
        host=os.environ["TIGER_DB_PGHOST"],
        port=os.environ["TIGER_DB_PGPORT"],
        dbname=os.environ["TIGER_DB_PGDATABASE"],
        user=os.environ["TIGER_DB_PGUSER"],
        password=os.environ["TIGER_DB_PGPASSWORD"],
        sslmode=os.environ.get("TIGER_DB_PGSSLMODE", "require"),
        autocommit=True,
    )
    try:
        conn.execute("SET TIME ZONE 'UTC'")
        for statement in SQL_PATH.read_text().split(";"):
            sql = statement.strip()
            if sql:
                conn.execute(sql) # type: ignore
        print("Created discussion and backtest tables")
    finally:
        conn.close()


if __name__ == "__main__":
    load_discussions_backtests()
