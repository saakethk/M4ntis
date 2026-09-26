# Database
All the code necessary for initializing the database with the necessary data and schemas.

## User

## Algorithm

## Backtest

## Posts

## Market data

`schema_dev.ipynb` creates the Timescale hypertable `stock_minute_bars` and loads five years of 1-minute bars for AAPL and META from Alpaca. META bars before the 2022-06-09 rename are read as `FB` and stored as `META`.

Copy `.env.example` to `.env` in the repo root and fill in the Alpaca and Tiger Data variables, then run the notebook from the repo root. The default Alpaca feed is `iex`. Set `ALPACA_DATA_FEED=sip` when the account includes SIP.
