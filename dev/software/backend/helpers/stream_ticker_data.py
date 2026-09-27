"""Stream OHLCV bars for one symbol at a requested resolution.

Bars are aggregated from ``stock_minute_bars``. Buckets use ``America/New_York``
so intraday bars line up with the regular session and daily, weekly, and
monthly bars follow the exchange calendar day.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from psycopg.rows import dict_row

from dev.software.backend.helpers.db import connect

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
        allowed = ", ".join(RESOLUTIONS)
        raise ValueError(
            f"Unknown resolution {resolution!r}. Expected one of: {allowed}."
        ) from exc


def stream_ticker_data(
    symbol: str,
    resolution: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterator[dict]:
    """Yield OHLCV bars for ``symbol`` at ``resolution``.

    ``start`` is inclusive and ``end`` is exclusive. Each bar has ``ts``,
    ``open``, ``high``, ``low``, ``close``, and ``volume``.
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

    query = f"""
        SELECT
            time_bucket(%s::interval, ts, 'America/New_York') AS ts,
            first(open, ts) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, ts) AS close,
            sum(volume) AS volume
        FROM stock_minute_bars
        WHERE {" AND ".join(filters)}
        GROUP BY 1
        ORDER BY 1
    """

    conn = connect()
    try:
        with conn.transaction():
            with conn.cursor(name="ticker_bars", row_factory=dict_row) as cur:
                cur.itersize = 1000
                cur.execute(query, params) # type: ignore
                yield from (dict(row) for row in cur)
    finally:
        conn.close()
