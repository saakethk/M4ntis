"""Load five years of Alpaca 1-minute bars into Timescale."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv
from psycopg import generators, pq
from psycopg.rows import dict_row

load_dotenv()

ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
META_RENAME = datetime(2022, 6, 9, tzinfo=timezone.utc)
WINDOW = timedelta(days=31)
SQL_DIR = Path(__file__).resolve().parent / "sql"
UNIQUE_INDEX_MARKER = "-- @@unique-index"
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
    conn = psycopg.connect(
        host=os.environ["TIGER_DB_PGHOST"],
        port=os.environ["TIGER_DB_PGPORT"],
        dbname=os.environ["TIGER_DB_PGDATABASE"],
        user=os.environ["TIGER_DB_PGUSER"],
        password=os.environ["TIGER_DB_PGPASSWORD"],
        sslmode=os.environ.get("TIGER_DB_PGSSLMODE", "require"),
        autocommit=True,
    )
    # Naive timestamps cast to timestamptz in the session time zone. Pin UTC
    # so the same bar is the same instant on every run.
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


def split_sql(script: str) -> list[str]:
    """Split a SQL script on semicolons, keeping dollar-quoted bodies intact."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    length = len(script)
    dollar_tag: str | None = None
    while i < length:
        if dollar_tag is not None:
            if script.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(script[i])
            i += 1
            continue

        if script.startswith("--", i):
            newline = script.find("\n", i)
            i = length if newline == -1 else newline + 1
            continue

        if script[i] == "'":
            buf.append(script[i])
            i += 1
            while i < length:
                buf.append(script[i])
                if script[i] == "'":
                    if i + 1 < length and script[i + 1] == "'":
                        buf.append(script[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if script[i] == "$":
            end = i + 1
            while end < length and (script[end].isalnum() or script[end] == "_"):
                end += 1
            if end < length and script[end] == "$":
                dollar_tag = script[i : end + 1]
                buf.append(dollar_tag)
                i = end + 1
                continue

        if script[i] == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(script[i])
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _command_in_progress(conn: psycopg.Connection) -> bool:
    """True while libpq still has a COPY or query in flight."""
    return (
        conn.pgconn.status == pq.ConnStatus.OK
        and conn.pgconn.transaction_status == pq.TransactionStatus.ACTIVE
    )


def _release_in_progress_command(conn: psycopg.Connection) -> None:
    """Finish a COPY or other command before another statement or ROLLBACK.

    ``Connection.transaction()`` sends ROLLBACK when its block exits with an
    error. If that happens while COPY is still active, libpq refuses the
    ROLLBACK with "another command is already in progress" and the connection
    stays unusable. The copy context is supposed to cancel first; if its
    flush fails before ``PQputCopyEnd``, the connection is still ACTIVE and
    this finishes the command.
    """
    if not _command_in_progress(conn):
        return

    try:
        conn.wait(
            generators.copy_end(conn.pgconn, b"copy aborted before rollback"),
            timeout=5.0,
        )
    except Exception:
        pass

    if not _command_in_progress(conn):
        return

    try:
        conn.cancel_safe(timeout=5.0)
    except Exception:
        try:
            conn.cancel()
        except Exception:
            return

    if not _command_in_progress(conn):
        return

    try:
        conn.wait(generators.execute(conn.pgconn), timeout=5.0)
    except Exception:
        return


def _require_idle_session(conn: psycopg.Connection) -> None:
    """Refuse pipeline mode, and drop a command left over from an earlier error.

    Pipeline mode and COPY cannot run on the same connection. A cursor left
    open from the dedupe query must also be finished before the next command.
    """
    if conn.pgconn.pipeline_status:
        raise RuntimeError(
            "stock_minute_bars cannot be loaded while the connection is in "
            "pipeline mode"
        )
    _release_in_progress_command(conn)


def execute_sql_script(conn: psycopg.Connection, script: str) -> None:
    with conn.cursor() as cur:
        for statement in split_sql(script):
            # One statement at a time. Never send the next while the previous
            # result or COPY is still in progress.
            _release_in_progress_command(conn)
            cur.execute(statement)  # type: ignore


def parse_bar_ts(value: str) -> datetime:
    """Return the bar instant as a UTC ``timestamptz`` value.

    Naive strings are treated as UTC. Aware strings are converted to UTC so
    the same instant is not stored twice under two offsets.
    """
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    fraction = text.find(".")
    if fraction != -1:
        zone = max(text.find("+", fraction), text.find("-", fraction))
        digits_end = zone if zone != -1 else len(text)
        digits = text[fraction + 1 : digits_end]
        if len(digits) > 6:
            text = text[: fraction + 1] + digits[:6] + text[digits_end:]
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def alpaca_inclusive_end(window_end: datetime) -> datetime:
    """Alpaca's ``end`` is inclusive. Shift it so ``[start, window_end)`` is fetched."""
    return window_end - timedelta(microseconds=1)


def canonical_ts(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def delete_duplicate_rows(conn: psycopg.Connection) -> int:
    """Run ``dedupe_stock_minute_bars()`` and close the cursor before returning.

    ``Connection.execute()`` leaves its cursor open. The next statement (the
    unique index, or a COPY) must not start while that result is still current.
    """
    _require_idle_session(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT dedupe_stock_minute_bars()")
        removed = cur.fetchone()
    return int(removed[0]) if removed else 0


def ensure_hypertable(conn: psycopg.Connection) -> None:
    """Create the hypertable, drop exact duplicates, then ensure the unique key."""
    _require_idle_session(conn)
    schema = (SQL_DIR / "stock_minute_bars.sql").read_text()
    if UNIQUE_INDEX_MARKER not in schema:
        raise RuntimeError(
            "stock_minute_bars.sql is missing the unique-index section"
        )
    before, _, after = schema.partition(UNIQUE_INDEX_MARKER)
    execute_sql_script(conn, before)
    execute_sql_script(conn, (SQL_DIR / "dedupe_stock_minute_bars.sql").read_text())
    removed_count = delete_duplicate_rows(conn)
    if removed_count:
        print(f"Removed {removed_count} duplicate stock_minute_bars rows")
    execute_sql_script(conn, after)
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
        ts = parse_bar_ts(bar["t"])
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
    """Page through Alpaca minute bars for the half-open interval ``[start, end)``.

    Alpaca treats both ``start`` and ``end`` as inclusive. The requested end
    is one microsecond before ``end`` so the next window can start at ``end``
    without fetching that minute again.
    """
    inclusive_end = alpaca_inclusive_end(end)
    if inclusive_end < start:
        return []
    rows: list[tuple] = []
    page_token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Min",
            "start": start.isoformat(),
            "end": inclusive_end.isoformat(),
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
    """Keep one row per ``(symbol, ts)``, preferring a native bar over FB.

    The rank column stays on the row so the insert can apply the same
    preference if both copies reach the stage table. Rank 0 is native.
    """
    deduped: dict[tuple, tuple] = {}
    rank: dict[tuple, int] = {}
    for row in rows:
        ts = canonical_ts(row[1])
        stored = (row[0], ts, *row[2:])
        key = (stored[0], ts)
        row_rank = stored[-1]
        if key not in deduped or row_rank < rank[key]:
            deduped[key] = stored
            rank[key] = row_rank
    return list(deduped.values())


def insert_rows(conn: psycopg.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    values = prefer_native_bars(rows)
    # autocommit stays on for DDL. This block is the only transaction.
    # Exit the COPY context, and finish it if the flush failed, before the
    # INSERT and before this context sends COMMIT or ROLLBACK. ROLLBACK while
    # COPY is active is ignored as "another command is already in progress".
    _require_idle_session(conn)
    with conn.transaction():
        try:
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
                        vwap DOUBLE PRECISION,
                        source_rank SMALLINT NOT NULL
                    ) ON COMMIT DROP
                    """
                )
                try:
                    with cur.copy(
                        """
                        COPY stock_minute_bars_stage (
                            symbol, ts, open, high, low, close, volume,
                            trade_count, vwap, source_rank
                        ) FROM STDIN
                        """
                    ) as copy:
                        for row in values:
                            copy.write_row(row)
                finally:
                    _release_in_progress_command(conn)
                cur.execute(
                    """
                    INSERT INTO stock_minute_bars (
                        symbol, ts, open, high, low, close, volume, trade_count, vwap
                    )
                    SELECT DISTINCT ON (symbol, ts)
                        symbol, ts, open, high, low, close, volume, trade_count, vwap
                    FROM stock_minute_bars_stage
                    ORDER BY symbol, ts, source_rank
                    ON CONFLICT (symbol, ts) DO NOTHING
                    """
                )
                inserted = cur.rowcount
        finally:
            _release_in_progress_command(conn)
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


def load_minute_bars(symbols: list[str], years_past: int = 5) -> None:
    feed = load_environment()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=365 * years_past)
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

def get_symbols(file_path: str) -> list[str]:
    # reads a list of symbols in from a file path

    with open(file_path, "r") as f:
        symbols = [item.replace("\n", "").strip() for item in f.readlines()]
        return symbols

    return []

if __name__ == "__main__":
    
    # nasdaq_stocks = get_symbols("symbols/nasdaq.txt")
    # load_minute_bars(nasdaq_stocks, years_past=1)

    sponsor_stocks = get_symbols("symbols/sponsors.txt")
    load_minute_bars(sponsor_stocks, years_past=5)
