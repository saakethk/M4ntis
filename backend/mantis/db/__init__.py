"""PostgreSQL (Tiger Data) connections.

Every service opens a short-lived connection with :func:`session`. Connections run
in autocommit mode, so a single read needs no transaction and a write that must be
atomic wraps its statements in ``with conn.transaction():``. The first session in a
process creates any missing tables (see :mod:`mantis.db.schema`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from backend.mantis.config import env
from backend.mantis.db.schema import ensure_schema
from backend.mantis.errors import ServiceUnavailable

REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)


class DatabaseUnavailable(ServiceUnavailable):
    def __init__(self, detail: str = "Database is unavailable"):
        super().__init__(detail)


def connect() -> psycopg.Connection:
    """Open an autocommit connection in UTC. Raises DatabaseUnavailable when it can't."""
    missing = [name for name in REQUIRED_ENV if not env(name)]
    if missing:
        raise DatabaseUnavailable("Database is not configured. Missing " + ", ".join(missing))
    try:
        conn = psycopg.connect(
            host=env("TIGER_DB_PGHOST"),
            port=env("TIGER_DB_PGPORT"),
            dbname=env("TIGER_DB_PGDATABASE"),
            user=env("TIGER_DB_PGUSER"),
            password=env("TIGER_DB_PGPASSWORD"),
            sslmode=env("TIGER_DB_PGSSLMODE", "require"),
            autocommit=True,
        )
    except psycopg.Error as exc:
        raise DatabaseUnavailable() from exc
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


@contextmanager
def session() -> Iterator[psycopg.Connection]:
    """A connection with the schema in place, closed when the block exits."""
    conn = connect()
    try:
        ensure_schema(conn)
        yield conn
    finally:
        conn.close()
