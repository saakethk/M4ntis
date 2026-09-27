"""Stream OHLCV bars for one symbol at a requested resolution.

Bars are aggregated from ``stock_minute_bars`` with TimescaleDB's ``time_bucket``.
Buckets use ``America/New_York`` so intraday bars line up with the regular session
and daily, weekly, and monthly bars follow the exchange calendar. This is the data
source a real backtester will read; no route exposes it yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from psycopg.rows import dict_row

from mantis import db
from mantis.errors import InvalidInput

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


def resolution_interval(resolution: str) -> str:
    try:
        return RESOLUTIONS[resolution.strip().lower()]
    except KeyError as exc:
        raise InvalidInput(
            f"Unknown resolution {resolution!r}. Expected one of: {', '.join(RESOLUTIONS)}."
        ) from exc


def stream_bars(
    symbol: str,
    resolution: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterator[dict]:
    """Yield ``{ts, open, high, low, close, volume}`` bars. ``start`` is inclusive, ``end`` exclusive."""
    ticker = symbol.strip().upper()
    if not ticker:
        raise InvalidInput("symbol is required")
    filters = ["symbol = %s"]
    params: list = [resolution_interval(resolution), ticker]
    if start is not None:
        filters.append("ts >= %s")
        params.append(start)
    if end is not None:
        filters.append("ts < %s")
        params.append(end)
    query = f"""
        SELECT time_bucket(%s::interval, ts, 'America/New_York') AS ts,
               first(open, ts) AS open, max(high) AS high, min(low) AS low,
               last(close, ts) AS close, sum(volume) AS volume
        FROM stock_minute_bars
        WHERE {" AND ".join(filters)}
        GROUP BY 1
        ORDER BY 1
    """
    with db.session() as conn, conn.transaction():
        # A named (server-side) cursor streams rows instead of loading them all.
        with conn.cursor(name="ticker_bars", row_factory=dict_row) as cursor:
            cursor.itersize = 1000
            cursor.execute(query, params)  # type: ignore[arg-type]
            yield from (dict(row) for row in cursor)
