"""Build forward-filled session minutes for a naive close-price backtest.

``trading_minutes`` is one row per regular-session minute from ``trading_days``.
``stock_session_minutes`` keeps only sessions that contain at least one real
bar for the symbol. Inside those sessions, a minute with no trade copies the
previous close forward and stores volume 0. The previous session's close fills
the next open only when that next session also has a trade. Empty sessions
are not synthesized.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SQL_DIR = Path(__file__).resolve().parent / "sql"
# A recycled ticker usually goes quiet for months. 60 skipped NYSE sessions
# is about three months. The current listing starts after the last gap at
# least this long.
LISTING_GAP_SESSIONS = 60
REQUIRED_ENV = (
    "TIGER_DB_PGHOST",
    "TIGER_DB_PGPORT",
    "TIGER_DB_PGDATABASE",
    "TIGER_DB_PGUSER",
    "TIGER_DB_PGPASSWORD",
)

FILL_SQL = """
INSERT INTO stock_session_minutes (
    symbol, ts, open, high, low, close, volume, is_filled
)
WITH bars AS (
    SELECT DISTINCT ON (date_trunc('minute', ts))
        date_trunc('minute', ts) AS ts,
        open,
        high,
        low,
        close,
        volume
    FROM stock_minute_bars
    WHERE symbol = %s
    ORDER BY date_trunc('minute', ts), ts
),
active_all AS (
    SELECT DISTINCT m.session_date
    FROM trading_minutes AS m
    JOIN bars AS b ON b.ts = m.ts
),
ordered AS (
    SELECT
        session_date,
        lag(session_date) OVER (ORDER BY session_date) AS prev_session
    FROM active_all
),
gaps AS (
    SELECT
        ordered.session_date AS resume_on,
        (
            SELECT count(*)
            FROM trading_days AS d
            WHERE d.session_date > ordered.prev_session
              AND d.session_date < ordered.session_date
        ) AS skipped_sessions
    FROM ordered
    WHERE ordered.prev_session IS NOT NULL
),
listing AS (
    SELECT COALESCE(
        (SELECT max(resume_on) FROM gaps WHERE skipped_sessions >= %s),
        DATE '-infinity'
    ) AS start_on
),
active AS (
    SELECT active_all.session_date
    FROM active_all
    CROSS JOIN listing
    WHERE active_all.session_date >= listing.start_on
),
joined AS (
    SELECT
        m.ts,
        b.open,
        b.high,
        b.low,
        b.close,
        b.volume,
        b.ts IS NOT NULL AS has_trade,
        count(b.close) OVER (ORDER BY m.ts) AS grp
    FROM trading_minutes AS m
    JOIN active AS a ON a.session_date = m.session_date
    LEFT JOIN bars AS b ON b.ts = m.ts
),
carried AS (
    SELECT
        *,
        max(close) OVER (
            PARTITION BY grp
            ORDER BY ts
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS last_close
    FROM joined
)
SELECT
    %s,
    ts,
    CASE WHEN has_trade THEN open ELSE last_close END,
    CASE WHEN has_trade THEN high ELSE last_close END,
    CASE WHEN has_trade THEN low ELSE last_close END,
    CASE WHEN has_trade THEN close ELSE last_close END,
    CASE WHEN has_trade THEN volume ELSE 0 END,
    NOT has_trade
FROM carried
WHERE grp > 0
"""


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


def collect_symbols(tickers: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        for item in ticker.split(","):
            symbol = item.strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            ordered.append(symbol)
    if not ordered:
        raise RuntimeError("Pass at least one symbol, for example AAPL META")
    return ordered


def execute_sql_file(conn: psycopg.Connection, name: str) -> None:
    script = (SQL_DIR / name).read_text()
    statement = []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        statement.append(line)
        if line.rstrip().endswith(";"):
            conn.execute("\n".join(statement))
            statement = []
    trailing = "\n".join(statement).strip()
    if trailing:
        conn.execute(trailing)


def rebuild_trading_minutes(conn: psycopg.Connection) -> int:
    count = conn.execute("SELECT count(*) FROM trading_days").fetchone()
    if count is None or count[0] == 0:
        raise RuntimeError(
            "trading_days is empty. Run software/database/load_trading_days.py first."
        )
    execute_sql_file(conn, "trading_minutes.sql")
    conn.execute("TRUNCATE trading_minutes")
    conn.execute(
        """
        INSERT INTO trading_minutes (ts, session_date)
        SELECT gs.ts, d.session_date
        FROM trading_days AS d
        CROSS JOIN LATERAL generate_series(
            d.open_at,
            d.close_at - INTERVAL '1 minute',
            INTERVAL '1 minute'
        ) AS gs(ts)
        """
    )
    minutes = conn.execute("SELECT count(*) FROM trading_minutes").fetchone()[0]
    print(f"trading_minutes: {minutes}")
    return int(minutes)


def ensure_session_table(conn: psycopg.Connection) -> None:
    execute_sql_file(conn, "stock_session_minutes.sql")


def fill_symbol(conn: psycopg.Connection, symbol: str) -> int:
    with conn.transaction():
        conn.execute(
            "DELETE FROM stock_session_minutes WHERE symbol = %s",
            (symbol,),
        )
        conn.execute(FILL_SQL, (symbol, LISTING_GAP_SESSIONS, symbol))
        stored = conn.execute(
            """
            SELECT count(*) FILTER (WHERE NOT is_filled) AS trades,
                   count(*) FILTER (WHERE is_filled) AS filled,
                   count(*) AS rows,
                   count(DISTINCT (ts AT TIME ZONE 'America/New_York')::date)
                       AS sessions
            FROM stock_session_minutes
            WHERE symbol = %s
            """,
            (symbol,),
        ).fetchone()
        raw = conn.execute(
            "SELECT count(*) FROM stock_minute_bars WHERE symbol = %s",
            (symbol,),
        ).fetchone()
        first = conn.execute(
            """
            SELECT min(ts AT TIME ZONE 'America/New_York')::date
            FROM stock_session_minutes
            WHERE symbol = %s
            """,
            (symbol,),
        ).fetchone()
    print(
        f"{symbol}: raw_bars={raw[0]} matched={stored[0]} "
        f"sessions={stored[3]} carried={stored[1]} rows={stored[2]} "
        f"listing_start={first[0]}"
    )
    return int(stored[2])


def build_session_minutes(symbols: list[str]) -> None:
    load_environment()
    conn = connect()
    try:
        rebuild_trading_minutes(conn)
        ensure_session_table(conn)
        for symbol in symbols:
            fill_symbol(conn, symbol)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Forward-fill minute closes onto the NYSE session clock."
    )
    parser.add_argument("symbols", nargs="+", help="Tickers, for example AAPL META")
    args = parser.parse_args()
    build_session_minutes(collect_symbols(args.symbols))


if __name__ == "__main__":
    main()
