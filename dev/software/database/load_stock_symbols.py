"""Load symbol-to-company-name rows into stock_symbols.

The committed file symbols/names.csv covers the Nasdaq-100 list plus the
sponsor tickers that are not in that index. When the Nasdaq-100 quote list
is reachable, those names are refreshed before the upsert.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

NASDAQ_100_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
DATABASE_DIR = Path(__file__).resolve().parent
SQL_PATH = DATABASE_DIR / "sql" / "stock_symbols.sql"
NAMES_PATH = DATABASE_DIR / "symbols" / "names.csv"
REQUIRED_ENV = (
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


def read_name_file(path: Path) -> dict[str, str]:
    """Read a symbol,name CSV. The first row is a header."""
    names: dict[str, str] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "symbol" not in reader.fieldnames or "name" not in reader.fieldnames:
            raise ValueError(f"{path} must have symbol and name columns")
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            name = " ".join((row.get("name") or "").split())
            if not symbol or not name:
                continue
            names[symbol] = name
    return names


def names_from_nasdaq_payload(payload: dict) -> dict[str, str]:
    """Pull symbol and companyName pairs out of the Nasdaq-100 quote list."""
    rows = payload.get("data", {}).get("data", {}).get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("Nasdaq-100 response did not include a row list")
    names: dict[str, str] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        name = " ".join(str(row.get("companyName") or "").split())
        if symbol and name:
            names[symbol] = name
    if not names:
        raise RuntimeError("Nasdaq-100 response did not include any names")
    return names


def fetch_nasdaq_names() -> dict[str, str]:
    response = requests.get(
        NASDAQ_100_URL,
        headers={"Accept": "application/json", "User-Agent": "gt-hacks-symbol-loader"},
        timeout=60,
    )
    response.raise_for_status()
    return names_from_nasdaq_payload(response.json())


def collect_names() -> dict[str, str]:
    """Start from the committed file, then refresh Nasdaq-100 names when possible."""
    names = read_name_file(NAMES_PATH)
    try:
        names.update(fetch_nasdaq_names())
    except requests.RequestException as exc:
        print(f"Nasdaq name list unavailable ({exc}); using {NAMES_PATH.name}")
    return names


def ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(SQL_PATH.read_text())


def upsert_names(conn: psycopg.Connection, names: dict[str, str]) -> int:
    rows = sorted(names.items())
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stock_symbols (symbol, name)
            VALUES (%s, %s)
            ON CONFLICT (symbol) DO UPDATE
            SET name = EXCLUDED.name
            """,
            rows,
        )
    return len(rows)


def load_stock_symbols() -> None:
    load_environment()
    names = collect_names()
    conn = connect()
    try:
        ensure_table(conn)
        written = upsert_names(conn, names)
        print(f"Upserted {written} symbols into stock_symbols")
    finally:
        conn.close()


if __name__ == "__main__":
    load_stock_symbols()
