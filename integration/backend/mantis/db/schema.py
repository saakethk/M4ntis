"""Create or upgrade the tables the backend uses, once per process.

The base tables live in ``software/database/sql`` so the data loaders and this
server share one definition. ``migrations.sql`` next to this file holds upgrades
that only the integration backend needs (older databases and new columns).
"""

from __future__ import annotations

import threading
from pathlib import Path

import psycopg

from mantis.config import DATABASE_SQL_DIR

SCHEMA_FILES: tuple[Path, ...] = (
    DATABASE_SQL_DIR / "users.sql",
    DATABASE_SQL_DIR / "strategies.sql",
    DATABASE_SQL_DIR / "discussions_backtests.sql",
    Path(__file__).with_name("migrations.sql"),
)

_lock = threading.Lock()
_ready = False


def ensure_schema(conn: psycopg.Connection) -> None:
    """Apply every schema file. Statements are idempotent, so reruns are harmless."""
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        with conn.transaction():
            for path in SCHEMA_FILES:
                # Without parameters psycopg sends the whole file as one script.
                conn.execute(path.read_text())
        _ready = True


def reset_for_tests() -> None:
    global _ready
    _ready = False
