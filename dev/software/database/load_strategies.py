"""Create the strategies table.

Run from the repository root after users exist:

    python software/database/load_users.py
    python software/database/load_strategies.py

A public strategy can be viewed by any signed-in user. Another user copies
it into a new private row they own. The loader drops strategy_shares when
an older load created that table.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SQL_PATH = Path(__file__).resolve().parent / "sql" / "strategies.sql"
REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)
VISIBILITY_CHECK = "strategies_visibility_check"
DROP_SHARES_SQL = "DROP TABLE IF EXISTS strategy_shares"
ADD_VISIBILITY_SQL = (
    "ALTER TABLE strategies "
    "ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'"
)


def find_repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def _add_visibility_check_if_missing(conn: psycopg.Connection) -> None:
    existing = conn.execute(
        """
        SELECT 1
        FROM pg_constraint
        WHERE conname = %s
          AND conrelid = 'strategies'::regclass
        """,
        (VISIBILITY_CHECK,),
    ).fetchone()
    if existing is not None:
        return
    conn.execute(
        """
        ALTER TABLE strategies
        ADD CONSTRAINT strategies_visibility_check
        CHECK (visibility IN ('private', 'public'))
        """
    )


def load_strategies() -> None:
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
        conn.execute(DROP_SHARES_SQL)
        conn.execute(ADD_VISIBILITY_SQL)
        _add_visibility_check_if_missing(conn)
        print("Created strategies")
    finally:
        conn.close()


if __name__ == "__main__":
    load_strategies()
