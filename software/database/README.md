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

## strategies

One saved strategy per row, owned by `user_id`. `document` is the React Flow file `m4ntis.strategy/v1`. `ir` is the compiled `m4ntis.strategy-ir/v1` and may be null.

`visibility` is `private` or `public`. A private strategy is visible only to its owner. A public strategy can be viewed by anyone who is signed in. Only the owner (`strategies.user_id`) can update or delete the row.

Another user gets their own strategy by copying. The copy is a new row with their `user_id`, `visibility` `private`, and the same `name`, `document`, and `ir`. The original row stays as it was.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| user_id | BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE |
| name | TEXT NOT NULL |
| visibility | TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'public')) |
| document | JSONB NOT NULL |
| ir | JSONB |
| updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Index: `strategies_user_id_idx` on `user_id`.

DDL: [`sql/strategies.sql`](sql/strategies.sql).

Users must already exist (`python software/database/load_users.py` first) because of the foreign key. Then create the table with `python software/database/load_strategies.py`. If an older database still has `strategy_shares`, the loader drops it. If `strategies` already exists without `visibility`, the loader adds that column (default `private`) and adds the check constraint when it is missing.

## discussion_posts

A forum post. `parent_id` null is a top-level post. A non-null `parent_id` is a comment, including a reply to another comment. `strategy_id` is optional. Attaching a strategy publishes it for viewing: the owner's private strategy becomes public. Deleting that strategy sets `strategy_id` to null and leaves the post. `likes_count` is the stored counter. The app updates it when a `discussion_likes` row is inserted or deleted.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| user_id | BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE |
| strategy_id | BIGINT REFERENCES strategies (id) ON DELETE SET NULL |
| parent_id | BIGINT REFERENCES discussion_posts (id) ON DELETE CASCADE |
| body | TEXT NOT NULL |
| likes_count | INTEGER NOT NULL DEFAULT 0 |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Indexes: `discussion_posts_parent_id_idx` on `parent_id`, `discussion_posts_strategy_id_idx` on `strategy_id`.

## discussion_likes

One like per user per post. The primary key stops the same person from liking a post twice, so `discussion_posts.likes_count` cannot be incremented twice for that person.

| Column | Type |
| --- | --- |
| post_id | BIGINT NOT NULL REFERENCES discussion_posts (id) ON DELETE CASCADE |
| user_id | BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Primary key: `(post_id, user_id)`.

## strategy_versions

Immutable snapshot of a strategy. `kind` is `save` or `backtest`. Creating, updating the document, copying, or reverting writes a `save` row. A backtest writes a `backtest` row and points at that id. A later save does not change an older row. Revert copies a `save` row back onto `strategies` and writes a new `save` row, so the older versions stay in the list.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| strategy_id | BIGINT NOT NULL REFERENCES strategies (id) ON DELETE CASCADE |
| document | JSONB NOT NULL |
| ir | JSONB |
| kind | TEXT NOT NULL DEFAULT 'save' |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Index: `strategy_versions_strategy_id_idx` on `strategy_id`.

## backtests

One row per run, tied to the `strategy_versions` snapshot and to the user who ran it.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| strategy_version_id | BIGINT NOT NULL REFERENCES strategy_versions (id) ON DELETE CASCADE |
| user_id | BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Index: `backtests_strategy_version_id_idx` on `strategy_version_id`.

## backtest_orders

Orders produced by one backtest. `side` is `buy` or `sell`.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| backtest_id | BIGINT NOT NULL REFERENCES backtests (id) ON DELETE CASCADE |
| ts | TIMESTAMPTZ NOT NULL |
| symbol | TEXT NOT NULL |
| side | TEXT NOT NULL CHECK (side IN ('buy', 'sell')) |
| quantity | DOUBLE PRECISION NOT NULL |
| price | DOUBLE PRECISION NOT NULL |

Index: `backtest_orders_backtest_id_ts_idx` on `(backtest_id, ts)`.

## backtest_balances

Cash and equity over time for one backtest.

| Column | Type |
| --- | --- |
| id | BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| backtest_id | BIGINT NOT NULL REFERENCES backtests (id) ON DELETE CASCADE |
| ts | TIMESTAMPTZ NOT NULL |
| cash | DOUBLE PRECISION NOT NULL |
| equity | DOUBLE PRECISION NOT NULL |

Index: `backtest_balances_backtest_id_ts_idx` on `(backtest_id, ts)`.

DDL: [`sql/discussions_backtests.sql`](sql/discussions_backtests.sql).

`users` and `strategies` must already exist (`python software/database/load_users.py`, then `python software/database/load_strategies.py`) because of the foreign keys. Then create these tables with `python software/database/load_discussions_backtests.py`.

