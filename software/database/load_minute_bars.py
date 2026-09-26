"""Load five years of Alpaca 1-minute bars into Timescale.

Creates the ``stock_minute_bars`` hypertable if needed, pulls 1-minute bars
from Alpaca, and copies them into Tiger Data with ``ON CONFLICT DO NOTHING``.

Credentials are read from the repo-root ``.env`` file (``ALPACA_API_KEY``,
``ALPACA_API_SECRET``, and ``TIGER_DB_PG*``). The default data feed is
``iex``. Override it with ``ALPACA_DATA_FEED``. Secret values are never printed.

When META is one of the requested tickers, bars before the 2022-06-09 rename
are requested as FB and stored as META. A native META bar wins when both
exist for the same minute.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv
from psycopg.rows import dict_row

ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
META_RENAME = datetime(2022, 6, 9, tzinfo=timezone.utc)
WINDOW = timedelta(days=31)
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
    """Return the git root that holds ``.env``, starting from this file."""
    start = Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".git").exists():
            return candidate
    return cwd


def collect_symbols(tickers: list[str], symbols_arg: str | None) -> list[str]:
    """Uppercase and de-duplicate tickers from positional args and --symbols."""
    raw: list[str] = []
    if symbols_arg:
        raw.extend(symbols_arg.split(","))
    for ticker in tickers:
        raw.extend(ticker.split(","))

    ordered: list[str] = []
    seen: set[str] = set()
    for item in raw:
        symbol = item.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load five years of 1-minute Alpaca bars into the Timescale "
            "hypertable stock_minute_bars."
        ),
        epilog=(
            "examples:\n"
            "  python software/database/load_minute_bars.py AAPL META NVDA\n"
            "  python software/database/load_minute_bars.py --symbols AAPL,META\n"
            "  python software/database/load_minute_bars.py NVDA --symbols AAPL,META"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        metavar="TICKER",
        help="Ticker symbols to load, for example AAPL META NVDA",
    )
    parser.add_argument(
        "--symbols",
        metavar="LIST",
        help="Comma-separated ticker symbols, for example AAPL,META",
    )
    return parser


def load_environment() -> str:
    """Load the repo-root ``.env`` and return the Alpaca feed name."""
    load_dotenv(find_repo_root() / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env at the repo root and fill them in."
        )
    return os.environ.get("ALPACA_DATA_FEED", "iex")


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["TIGER_DB_PGHOST"],
        port=os.environ["TIGER_DB_PGPORT"],
        dbname=os.environ["TIGER_DB_PGDATABASE"],
        user=os.environ["TIGER_DB_PGUSER"],
        password=os.environ["TIGER_DB_PGPASSWORD"],
        sslmode=os.environ.get("TIGER_DB_PGSSLMODE", "require"),
        autocommit=True,
    )


def ensure_hypertable(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
        if cur.fetchone() is None:
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_minute_bars (
                symbol TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume BIGINT NOT NULL,
                trade_count BIGINT,
                vwap DOUBLE PRECISION,
                PRIMARY KEY (symbol, ts)
            )
            """
        )
        cur.execute(
            """
            SELECT create_hypertable(
                'stock_minute_bars',
                'ts',
                if_not_exists => TRUE,
                migrate_data => TRUE
            )
            """
        )
    print("stock_minute_bars is ready")


def symbols_for_window(symbols: list[str], window_start: datetime) -> list[str]:
    """Add FB for pre-rename windows only when META was requested."""
    requested = list(symbols)
    if "META" in symbols and window_start < META_RENAME and "FB" not in requested:
        requested.append("FB")
    return requested


def rows_from_bars(
    symbol: str,
    bars: list[dict],
    map_fb_to_meta: bool,
) -> list[tuple]:
    """Turn Alpaca bars into copy rows.

    The last element is a rank used only for de-duplication: 0 for a native
    symbol and 1 for an FB bar stored as META. Lower rank wins.
    """
    rows = []
    for bar in bars:
        ts = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        stored_symbol = symbol
        rank = 0
        if map_fb_to_meta and symbol == "FB":
            if ts >= META_RENAME:
                continue
            stored_symbol = "META"
            rank = 1
        rows.append(
            (
                stored_symbol,
                ts,
                bar["o"],
                bar["h"],
                bar["l"],
                bar["c"],
                bar["v"],
                bar.get("n"),
                bar.get("vw"),
                rank,
            )
        )
    return rows


def fetch_bars(
    session: requests.Session,
    symbols: list[str],
    start: datetime,
    end: datetime,
    feed: str,
    map_fb_to_meta: bool,
) -> list[tuple]:
    """Page through Alpaca minute bars for one time window."""
    rows: list[tuple] = []
    page_token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Min",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "adjustment": "split",
            "feed": feed,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token

        response = None
        for attempt in range(5):
            response = session.get(ALPACA_BARS_URL, params=params, timeout=60)
            if response.status_code != 429:
                break
            retry_after = int(response.headers.get("Retry-After", "2"))
            time.sleep(retry_after + attempt)
        if response is None:
            raise RuntimeError("Alpaca request was not sent")
        if response.status_code == 403:
            raise RuntimeError(
                "Alpaca rejected the data feed "
                f"'{feed}'. The free plan uses iex. "
                "Set ALPACA_DATA_FEED=sip only if the account includes SIP. "
                f"Response: {response.text[:300]}"
            )
        response.raise_for_status()
        payload = response.json()
        for symbol, bars in (payload.get("bars") or {}).items():
            rows.extend(rows_from_bars(symbol, bars, map_fb_to_meta))
        page_token = payload.get("next_page_token")
        if not page_token:
            return rows


def prefer_native_bars(rows: list[tuple]) -> list[tuple]:
    """Drop the rank column, keeping the native META bar on timestamp ties."""
    deduped: dict[tuple, tuple] = {}
    rank: dict[tuple, int] = {}
    for row in rows:
        key = (row[0], row[1])
        row_rank = row[-1]
        if key not in deduped or row_rank < rank[key]:
            deduped[key] = row[:-1]
            rank[key] = row_rank
    return list(deduped.values())


def insert_rows(conn: psycopg.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    values = prefer_native_bars(rows)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE stock_minute_bars_stage (
                    symbol TEXT NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    volume BIGINT NOT NULL,
                    trade_count BIGINT,
                    vwap DOUBLE PRECISION
                ) ON COMMIT DROP
                """
            )
            with cur.copy(
                """
                COPY stock_minute_bars_stage (
                    symbol, ts, open, high, low, close, volume, trade_count, vwap
                ) FROM STDIN
                """
            ) as copy:
                for row in values:
                    copy.write_row(row)
            cur.execute(
                """
                INSERT INTO stock_minute_bars
                SELECT DISTINCT ON (symbol, ts)
                    symbol, ts, open, high, low, close, volume, trade_count, vwap
                FROM stock_minute_bars_stage
                ORDER BY symbol, ts
                ON CONFLICT (symbol, ts) DO NOTHING
                """
            )
            inserted = cur.rowcount
    return inserted


def print_summary(conn: psycopg.Connection, symbols: list[str]) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT symbol,
                   count(*) AS rows,
                   min(ts) AS first_bar,
                   max(ts) AS last_bar
            FROM stock_minute_bars
            WHERE symbol = ANY(%s)
            GROUP BY symbol
            ORDER BY symbol
            """,
            (symbols,),
        )
        summary = cur.fetchall()

    for row in summary:
        print(
            f"{row['symbol']}: rows={row['rows']} "
            f"first={row['first_bar']} last={row['last_bar']}"
        )

    found = {row["symbol"] for row in summary}
    missing_symbols = [symbol for symbol in symbols if symbol not in found]
    if missing_symbols:
        raise RuntimeError(f"No bars stored for {', '.join(missing_symbols)}")


def load_minute_bars(symbols: list[str]) -> None:
    feed = load_environment()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=365 * 5)
    map_fb_to_meta = "META" in symbols

    print(
        f"Window {start.isoformat()} -> {end.isoformat()} "
        f"feed={feed} symbols={','.join(symbols)}"
    )

    session = requests.Session()
    session.headers.update(
        {
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
        }
    )

    conn = connect()
    try:
        ensure_hypertable(conn)
        window_start = start
        total_fetched = 0
        total_inserted = 0
        while window_start < end:
            window_end = min(window_start + WINDOW, end)
            request_symbols = symbols_for_window(symbols, window_start)
            rows = fetch_bars(
                session,
                request_symbols,
                window_start,
                window_end,
                feed,
                map_fb_to_meta,
            )
            inserted = insert_rows(conn, rows)
            total_fetched += len(rows)
            total_inserted += inserted
            print(
                f"{window_start.date()} -> {window_end.date()}: "
                f"fetched {len(rows)} inserted {inserted}"
            )
            window_start = window_end
        print(f"Done. fetched={total_fetched} inserted={total_inserted}")
        print_summary(conn, symbols)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    symbols = collect_symbols(args.tickers, args.symbols)
    if not symbols:
        parser.error("at least one ticker is required")
    load_minute_bars(symbols)


if __name__ == "__main__":
    main()
