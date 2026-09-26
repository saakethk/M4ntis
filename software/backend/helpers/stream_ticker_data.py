"""Stream OHLCV bars for one symbol at a requested resolution.

Bars are aggregated from ``stock_minute_bars`` in Tiger Data. Buckets use
``America/New_York`` so intraday bars line up with the regular session and
daily, weekly, and monthly bars follow the exchange calendar day.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

RESOLUTIONS = {
    "1min": "1 minute",
    "5min": "5 minutes",
    "15min": "15 minutes",
    "30min": "30 minutes",
    "1hour": "1 hour",
    "1day": "1 day",
    "1week": "1 week",
    "1month": "1 month",
}

REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)


def resolution_interval(resolution: str) -> str:
    """Return the Timescale bucket size for a resolution name."""
    try:
        return RESOLUTIONS[resolution.strip().lower()]
    except KeyError as exc:
        allowed = ", ".join(RESOLUTIONS)
        raise ValueError(
            f"Unknown resolution {resolution!r}. Expected one of: {allowed}."
        ) from exc


def _find_repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def _connect() -> psycopg.Connection:
    load_dotenv(_find_repo_root() / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )
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


def stream_ticker_data(
    symbol: str,
    resolution: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterator[dict]:
    """Yield OHLCV bars for ``symbol`` at ``resolution``.

    ``resolution`` is one of ``1min``, ``5min``, ``15min``, ``30min``,
    ``1hour``, ``1day``, ``1week``, or ``1month``. ``start`` is inclusive and
    ``end`` is exclusive. Each bar is a dict with ``ts``, ``open``, ``high``,
    ``low``, ``close``, and ``volume``.
    """
    ticker = symbol.strip().upper()
    if not ticker:
        raise ValueError("symbol is required")
    bucket = resolution_interval(resolution)

    filters = ["symbol = %s"]
    params: list = [bucket, ticker]
    if start is not None:
        filters.append("ts >= %s")
        params.append(start)
    if end is not None:
        filters.append("ts < %s")
        params.append(end)
    where = " AND ".join(filters)

    query = f"""
        SELECT
            time_bucket(%s::interval, ts, 'America/New_York') AS ts,
            first(open, ts) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, ts) AS close,
            sum(volume) AS volume
        FROM stock_minute_bars
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """

    conn = _connect()
    try:
        with conn.transaction():
            with conn.cursor(name="ticker_bars", row_factory=dict_row) as cur:
                cur.itersize = 1000
                cur.execute(query, params) # type: ignore
                for row in cur:
                    yield dict(row)
    finally:
        conn.close()

def test():
    
    ticker_gen = stream_ticker_data("AAPL", "1month")

    num_ticks = 0
    for tick in ticker_gen:
        num_ticks += 1
        print(tick)

    print(num_ticks)

if __name__ == "__main__":
    test()