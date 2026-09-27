# Services

Domain logic and SQL. Each module opens a short-lived connection with `db.session()`
and wraps writes that must be atomic in `conn.transaction()`.

| Module | Responsibility |
| --- | --- |
| `auth.py` | Accounts (scrypt password hashes) and sessions (only the SHA-256 of the token is stored) |
| `strategies.py` | Strategy CRUD, private/public visibility, copies, and `save` versions with revert. Other users' private strategies read as 404 |
| `compiler.py` | Expands macro blocks, runs the TradeCPU compiler from `software/compiler`, and maps diagnostics back to the blocks the user placed |
| `backtests.py` | Stores runs (a `backtest` strategy snapshot plus orders and balances) and derives metrics: return, drawdown, CAGR, Sharpe, FIFO trade P&L. Runs use a fixed sample series until the simulator exists; only `sample_orders`/`sample_balances` need replacing |
| `discussions.py` | Posts, replies, likes, publishing an attached strategy, and cached thread summaries (the summarizer is passed in, so this module has no AI dependency) |
| `symbols.py` | Ticker and company-name search, cached in memory for five minutes |
| `market_data.py` | Streams OHLCV bars at any resolution from TimescaleDB, for the future backtester |
