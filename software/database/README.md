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

Load bars with `python software/database/load_minute_bars.py AAPL`.
