# Services

Domain logic and SQL. Each module opens a short-lived connection with `db.session()`
and wraps writes that must be atomic in `conn.transaction()`.

| Module | Responsibility |
| --- | --- |
| `auth.py` | Accounts (scrypt password hashes) and sessions (only the SHA-256 of the token is stored) |
| `strategies.py` | Strategy CRUD, private/public visibility, copies, and `save` versions with revert. Other users' private strategies read as 404 |
| `compiler.py` | Expands macro blocks, runs the TradeCPU compiler from `software/compiler`, and maps diagnostics back to the blocks the user placed |
| `backtests.py` | Runs a strategy on the FPGA: compiles it, loads recent bars, scales each stock's prices to fit the board's 16-bit tick field, recompiles, and stores the board's decisions as orders and its balance after every tick (plus a `backtest` strategy snapshot). Derives metrics: return, drawdown, CAGR, Sharpe, FIFO trade P&L. There is no software fallback |
| `backtest_summaries.py` | The latest backtest of each strategy a user owns, with return, drawdown, and trade count, for `GET /strategies` |
| `fpga.py` | Serial link to the TradeCPU board (`FPGA_SERIAL_PORT`, `FPGA_BAUD`) using the framing in `software/compiler/tradecpu/hwtest.py`: board status, one run at a time (409 when busy), and 503 when the board is missing or stops answering |
| `discussions.py` | Posts, replies, likes, publishing an attached strategy, and cached thread summaries (the summarizer is passed in, so this module has no AI dependency) |
| `symbols.py` | Ticker and company-name search, cached in memory for five minutes |
| `market_data.py` | Streams OHLCV bars at any resolution from TimescaleDB, and `latest_closes` gives backtests the most recent closes where every symbol has a bar |
