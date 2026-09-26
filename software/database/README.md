# Database
All the code necessary for initializing the database with the necessary data and schemas.

## User

## Algorithm

## Backtest

## Posts

## Market data

`load_minute_bars.py` creates the Timescale hypertable `stock_minute_bars` and loads five years of 1-minute bars from Alpaca. Pass at least one ticker. Symbols are uppercased. Positional tickers and `--symbols` can be combined.

```bash
python software/database/load_minute_bars.py AAPL META NVDA
python software/database/load_minute_bars.py --symbols AAPL,META
python software/database/load_minute_bars.py NVDA --symbols AAPL,META
```

When `META` is one of the requested tickers, bars before the 2022-06-09 rename are requested as `FB` and stored as `META`. If an `FB` bar and a native `META` bar share a minute, the native `META` bar is kept. Other tickers are stored under the symbol you passed.

Copy `.env.example` to `.env` in the repo root and fill in `ALPACA_API_KEY`, `ALPACA_API_SECRET`, and the `TIGER_DB_PG*` variables. The script reads that file and does not print secret values. The default Alpaca feed is `iex`. Set `ALPACA_DATA_FEED=sip` when the account includes SIP.

Rows are copied into Tiger Data and inserted with `ON CONFLICT DO NOTHING`, so a later run does not duplicate bars. The script then prints each requested symbol's row count and earliest and latest timestamps.
