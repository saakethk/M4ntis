"""Load Alpaca's US market calendar into trading_days.

The default window is the same five-year span the minute-bar loader uses:
today, going back five years. Each row is one NYSE session, including
holidays omitted and early closes stored as an earlier close_at.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import requests
from dotenv import load_dotenv

ALPACA_CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
NEW_YORK = ZoneInfo("America/New_York")
SQL_PATH = Path(__file__).resolve().parent / "sql" / "trading_days.sql"
REQUIRED_ENV = (
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
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


def load_environment() -> None:
    load_dotenv(find_repo_root() / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env at the repo root and fill them in."
        )


def connect() -> psycopg.Connection:
    conn = psycopg.connect(
        host=os.environ["TIGER_DB_PGHOST"],
        port=os.environ["TIGER_DB_PGPORT"],
        dbname=os.environ["TIGER_DB_PGDATABASE"],
        user=os.environ["TIGER_DB_PGUSER"],
        password=os.environ["TIGER_DB_PGPASSWORD"],
        sslmode=os.environ.get("TIGER_DB_PGSSLMODE", "require"),
        autocommit=True,
    )
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


def calendar_window(years: int, today: date | None = None) -> tuple[date, date]:
    """Return the inclusive date span covering ``years`` back from today."""
    if years < 1:
        raise ValueError("years must be at least 1")
    end = today or datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * years)
    return start, end


def parse_clock(value: str) -> time:
    """Parse Alpaca's ``HH:MM`` or ``HHMM`` session clock."""
    text = value.strip()
    if ":" in text:
        hour, minute = text.split(":", 1)
    else:
        hour, minute = text[:2], text[2:4]
    return time(int(hour), int(minute))


def session_bounds(day: date, open_clock: str, close_clock: str) -> tuple[datetime, datetime]:
    """Return regular-session bounds as timezone-aware New York timestamps."""
    open_at = datetime.combine(day, parse_clock(open_clock), tzinfo=NEW_YORK)
    close_at = datetime.combine(day, parse_clock(close_clock), tzinfo=NEW_YORK)
    if close_at <= open_at:
        raise ValueError(f"{day.isoformat()} closes at or before it opens")
    return open_at, close_at


def fetch_calendar(session: requests.Session, start: date, end: date) -> list[dict]:
    """Page the calendar a year at a time. ``end`` is inclusive."""
    days: list[dict] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=365), end)
        response = session.get(
            ALPACA_CALENDAR_URL,
            params={"start": cursor.isoformat(), "end": window_end.isoformat()},
            timeout=60,
        )
        if response.status_code == 401:
            raise RuntimeError(
                "Alpaca rejected the calendar request. "
                "Check ALPACA_API_KEY and ALPACA_API_SECRET."
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Alpaca calendar response was not a list of sessions")
        days.extend(payload)
        cursor = window_end + timedelta(days=1)
    return days


def rows_from_calendar(days: list[dict]) -> list[tuple[date, datetime, datetime]]:
    rows: list[tuple[date, datetime, datetime]] = []
    seen: set[date] = set()
    for item in days:
        session_date = date.fromisoformat(item["date"])
        if session_date in seen:
            continue
        seen.add(session_date)
        open_at, close_at = session_bounds(session_date, item["open"], item["close"])
        rows.append((session_date, open_at, close_at))
    rows.sort(key=lambda row: row[0])
    return rows


def ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(SQL_PATH.read_text())


def upsert_days(
    conn: psycopg.Connection,
    rows: list[tuple[date, datetime, datetime]],
) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO trading_days (session_date, open_at, close_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (session_date) DO UPDATE
            SET open_at = EXCLUDED.open_at,
                close_at = EXCLUDED.close_at
            """,
            rows,
        )
    return len(rows)


def print_summary(conn: psycopg.Connection) -> None:
    row = conn.execute(
        """
        SELECT count(*) AS days,
               min(session_date) AS first_day,
               max(session_date) AS last_day,
               count(*) FILTER (
                   WHERE (close_at AT TIME ZONE 'America/New_York')::time < TIME '16:00'
               ) AS early_closes
        FROM trading_days
        """
    ).fetchone()
    print(
        f"trading_days: days={row[0]} first={row[1]} last={row[2]} "
        f"early_closes={row[3]}"
    )


def load_trading_days(years: int = 5) -> None:
    load_environment()
    start, end = calendar_window(years)
    print(f"Calendar {start.isoformat()} -> {end.isoformat()}")

    session = requests.Session()
    session.headers.update(
        {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
        }
    )
    days = fetch_calendar(session, start, end)
    rows = rows_from_calendar(days)
    if not rows:
        raise RuntimeError("Alpaca returned no trading days")

    conn = connect()
    try:
        ensure_table(conn)
        written = upsert_days(conn, rows)
        print(f"Upserted {written} sessions")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    load_trading_days(years=5)
