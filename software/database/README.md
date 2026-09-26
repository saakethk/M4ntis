# Database

## stock_minute_bars

1-minute equity bars. Timescale hypertable on `ts`.

| Column | Type |
| --- | --- |
| symbol | TEXT NOT NULL |
| ts | TIMESTAMPTZ NOT NULL |
| open | DOUBLE PRECISION NOT NULL |
| high | DOUBLE PRECISION NOT NULL |
| low | DOUBLE PRECISION NOT NULL |
| close | DOUBLE PRECISION NOT NULL |
| volume | BIGINT NOT NULL |
| trade_count | BIGINT |
| vwap | DOUBLE PRECISION |

Unique key: `(symbol, ts)`, including the `ts` partition column. A reload does not insert a second copy of the same minute. If that unique index is missing, the loader first deletes duplicate `(symbol, ts)` rows, then creates the index.

DDL: [`sql/stock_minute_bars.sql`](sql/stock_minute_bars.sql). Dedupe: [`sql/dedupe_stock_minute_bars.sql`](sql/dedupe_stock_minute_bars.sql).

Load bars with `python software/database/load_minute_bars.py`.

## trading_days

NYSE sessions from Alpaca's market calendar. One row per trading day, including early closes.

| Column | Type |
| --- | --- |
| session_date | DATE PRIMARY KEY |
| open_at | TIMESTAMPTZ NOT NULL |
| close_at | TIMESTAMPTZ NOT NULL |

`open_at` and `close_at` are the regular session in `America/New_York`. A reload updates the same date.

DDL: [`sql/trading_days.sql`](sql/trading_days.sql).

Load five years with `python software/database/load_trading_days.py`.

## trading_minutes

One row per regular-session minute, built from `trading_days`. The last minute of a session is `close_at` minus one minute.

| Column | Type |
| --- | --- |
| ts | TIMESTAMPTZ PRIMARY KEY |
| session_date | DATE NOT NULL |

DDL: [`sql/trading_minutes.sql`](sql/trading_minutes.sql).

## stock_session_minutes

Forward-filled minute bars for a naive backtest that fills at the current close. Only sessions that contain at least one real bar for the symbol are stored. A gap of 60 or more NYSE sessions is treated as a recycled ticker, and bars before the last such gap are ignored. Inside a kept session, a minute with no trade copies the previous close into open, high, low, and close, and stores volume 0. `is_filled` is true for those copied minutes. Timescale hypertable on `ts`.

| Column | Type |
| --- | --- |
| symbol | TEXT NOT NULL |
| ts | TIMESTAMPTZ NOT NULL |
| open | DOUBLE PRECISION NOT NULL |
| high | DOUBLE PRECISION NOT NULL |
| low | DOUBLE PRECISION NOT NULL |
| close | DOUBLE PRECISION NOT NULL |
| volume | BIGINT NOT NULL |
| is_filled | BOOLEAN NOT NULL |

Primary key: `(symbol, ts)`.

DDL: [`sql/stock_session_minutes.sql`](sql/stock_session_minutes.sql).

Build with `python software/database/build_session_minutes.py AAPL META`.

## stock_symbols

Company name for each ticker the symbol search can return. One row per symbol.

| Column | Type |
| --- | --- |
| symbol | TEXT PRIMARY KEY |
| name | TEXT NOT NULL |

A reload updates the name for the same symbol. The seed list is [`symbols/names.csv`](symbols/names.csv): the Nasdaq-100 names plus sponsor tickers that are not in that index (`V`, `GS`).

DDL: [`sql/stock_symbols.sql`](sql/stock_symbols.sql).

Load with `python software/database/load_stock_symbols.py`.

## users

One account per email. `password_hash` is a scrypt hash, not the password.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| email | TEXT NOT NULL UNIQUE |
| password_hash | TEXT NOT NULL |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

## sessions

One row per signed-in browser. `token_hash` is the SHA-256 of the cookie value. The cookie itself is not stored.

| Column | Type |
| --- | --- |
| token_hash | TEXT PRIMARY KEY |
| user_id | BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE |
| expires_at | TIMESTAMPTZ NOT NULL |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

DDL: [`sql/users.sql`](sql/users.sql).

Create both tables with `python software/database/load_users.py`.

