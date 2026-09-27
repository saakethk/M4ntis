# Mantis integration

The Mantis web platform: people build stock-trading strategies by wiring blocks in a
visual editor, get help from an AI agent that edits the blocks with them, compile the
result for TradeCPU (the FPGA processor in `hardware/`), backtest it, and discuss
strategies with other users.

This folder is the maintained version of `software/backend` and `software/frontend_prod`:

| Folder | What it is |
| --- | --- |
| [`backend/`](backend/README.md) | FastAPI server: accounts, strategies, compiler, backtests, discussions, AI assistant, post summaries |
| [`software/`](software/README.md) | React + Vite web app: portfolio, block editor, assistant, discussions, backtest reports |
| `dev.sh` | Starts both for local development |

It reuses two shared parts of the repository without copying them: the TradeCPU
compiler in `software/compiler` and the base SQL schemas in `software/database/sql`.

## System overview

```
Browser (integration/software)
  Portfolio ─ Editor (React Flow canvas, palette, Checks, Assistant, Backtest) ─ Discussions ─ Reports
        │  fetch + HttpOnly session cookie (Vite proxies API paths in development)
        ▼
FastAPI (integration/backend/mantis)
  api/       thin routers, request schemas, one error-to-HTTP mapping
  services/  auth, strategies + versions, compiler, backtests, discussions, symbols
  blocks/    block catalog, canvas validation, macro blocks (Z-Score)
  ai/        chat client (Gemini, Meta Muse, ...), strategy agent harness, post summaries
  db/        PostgreSQL sessions and schema bootstrap
        │                     │                              │
        ▼                     ▼                              ▼
PostgreSQL / Tiger Data   software/compiler (tradecpu)   Gemini API, Meta Model API
```

A strategy is saved as an `m4ntis.strategy/v1` JSON document: the canvas blocks,
their parameters, and the wires between them. The same document is what the
compiler reads, what version history stores, and what **Download JSON** writes, so
a downloaded program can be imported again, shared, or compiled from the command line.

## Running locally

Requirements: Python 3.12+, Node 22+, and a PostgreSQL database (Tiger Data in
production; any PostgreSQL 14+ works for everything except market-data bars).

1. Create the repo-root `.env` from the template and fill in the database settings:

   ```bash
   cp .env.example .env
   ```

   | Setting | Purpose |
   | --- | --- |
   | `TIGER_DB_PGHOST`, `_PGPORT`, `_PGDATABASE`, `_PGUSER`, `_PGPASSWORD`, `_PGSSLMODE` | Database connection (`TIGER_DB_PGSSLMODE=disable` for a local server) |
   | `GEMINI_API_KEY`, `META_API_KEY` | Enable those assistant models. `META_API_KEY` also enables post summaries |
   | `AI_PROVIDER`, `AI_MODEL` | Default assistant model, e.g. `gemini` / `gemini-3.8-flash` |
   | `BACKEND_PORT`, `FRONTEND_PORT` | Default 8001 and 8002 |
   | `FPGA_SERIAL_PORT`, `FPGA_BAUD` | TradeCPU board serial port (defaults to `COM4` on Windows; set e.g. `/dev/cu.usbserial-XXXX` on macOS/Linux) and baud rate (default 115200) |
   | `BACKTEST_TICKS` | Ticks per backtest after warm-up (default 500) |

   Tables are created automatically the first time the backend connects. Ticker
   search reads `stock_symbols`, which the loaders in `software/database` fill.

   Backtests run only on the TradeCPU FPGA: the board must be connected at
   `FPGA_SERIAL_PORT` (default `COM4`), and `stock_minute_bars` in TimescaleDB (Tiger) must hold
   minute bars for the strategy's stocks. Without the board, runs are refused with
   503 and the editor disables **Run on FPGA**.

2. Install dependencies:

   ```bash
   pip install -r integration/backend/requirements.txt
   npm install --prefix integration/software
   ```

3. Start both servers and open http://localhost:8002:

   ```bash
   ./integration/dev.sh
   ```

   Or run them separately with `python main.py` in `integration/backend` and
   `npm run dev` in `integration/software`.

## Testing

```bash
# Backend (database tests run only when MANTIS_TEST_DATABASE names a disposable database)
cd integration/backend
pip install -r requirements-dev.txt
MANTIS_TEST_DATABASE=postgresql://user:pass@127.0.0.1:5432/mantis_test python -m pytest

# Frontend: unit tests, then type-check and production build
cd integration/software
npm test
npm run build
```

## What changed from `software/`

- Backend split into layers (`api`, `services`, `blocks`, `ai`, `db`) with a single
  place that turns errors into HTTP responses, instead of per-route `try/except`.
- Frontend split into feature folders and a typed API layer; styles split by area.
- Editor: the raw compiled-assembly dump is gone. A **Checks** tab shows live checks
  and compiler results, and clicking one jumps to the block. Templates, JSON
  import/export, block search, and view-only mode with **Save a copy** were added.
- New **Z-Score** indicator block, expanded by the backend into compiler blocks.
- New tool-using **agent harness** behind the assistant; it edits the canvas step by
  step and checks its work with the compiler.
- **AI summaries** on discussion threads, written by Meta's Muse Spark.
- Assistant models updated to Gemini 3.x and Muse Spark. Retired Gemini 2.x and
  Llama 3.3 models are gone, and the model list comes from the server with
  per-provider availability.
- Portfolio controls that did nothing (play button, "View details", status filter,
  empty metrics) were replaced by working ones: visibility filter, JSON download,
  and import. The backtest panel's unused symbol/date/capital inputs were replaced
  by a summary of what the run actually uses.
