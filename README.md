# Mantis

**Design block-based stock-trading strategies, compile them for TradeCPU on an FPGA, backtest on real hardware with NASDAQ-100 minute data, and get AI help along the way.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![Verilog / FPGA](https://img.shields.io/badge/Verilog-FPGA-8C1515?logo=amd&logoColor=white)](src/hardware/)

Built for **GT Hacks Fall '26** ([`gt_hacks_fall_26`](https://github.com/saakethk/gt_hacks_fall_26)). Project site: [m4ntis.tech](https://m4ntis.tech) (GitHub Pages from this README).

---

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [How a strategy works](#how-a-strategy-works)
- [Block reference](#block-reference)
- [TradeCPU hardware](#tradecpu-hardware)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Testing](#testing)
- [API overview](#api-overview)
- [AI features](#ai-features)
- [Roadmap and known limitations](#roadmap-and-known-limitations)
- [Further reading](#further-reading)

---

## Overview

Mantis is a full-stack platform for **visual algorithmic trading**. You wire blocks in the browser—moving averages, conditions, buy/sell—and the backend compiles the graph to **TradeCPU machine code**, a custom ISA implemented in Verilog on a **Real Digital Urbana** board (Xilinx Spartan-7). Backtests do not simulate strategies in Python: they **stream historical bars from TimescaleDB**, scale prices for the FPGA, and drive the board over **UART** tick by tick. Decisions and balance come back from silicon.

That split—editor and data in the cloud, execution on dedicated hardware—is what makes Mantis different from a typical backtester. The same compiler powers live checks in the editor, the AI agent, and the FPGA runner.

---

## Features

| Area | What you get |
| --- | --- |
| **Visual editor** | React Flow canvas with exec and data ports, drag-and-drop palette, fit view, keyboard delete |
| **Templates** | Starter strategies (SMA crossover, mean reversion, and others) from built-in templates |
| **Import / export** | Save and load `m4ntis.strategy/v1` JSON (`.m4ntis.json`) from the portfolio and editor |
| **Checks panel** | Live graph validation plus on-demand compile; diagnostics link to the offending block |
| **AI strategy agent** | Tool-using harness (add/connect blocks, `check_strategy` via compiler); models from Gemini 3.x and Meta Muse Spark |
| **FPGA backtests** | Runs only on TradeCPU; date range from `GET /backtests/range` (days with minute data for every symbol the strategy reads) |
| **AI backtest analysis** | Ask a model to explain a finished run (metrics, equity curve, orders) and suggest improvements |
| **Discussions** | Forum with likes, replies, optional strategy attachments; **Muse Spark** thread summaries |
| **Version history** | Immutable `save` and `backtest` snapshots with restore |
| **Dark mode** | Light, dark, or follow system (`data-theme` on the document root) |
| **Blocks** | Indicators including **Z-Score** (macro expanded at compile time) and **Get Balance** (cash from the FPGA) |

---

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[React editor + discussions]
  end
  subgraph Backend["FastAPI (src/backend)"]
    API[api routes]
    SVC[services]
    BLK[blocks + macros]
    AI[ai client + agent]
    DBL[db bootstrap]
  end
  subgraph Data
    PG[(PostgreSQL / Tiger TimescaleDB)]
  end
  subgraph Build
    COMP[TradeCPU compiler]
  end
  subgraph Edge
    FPGA[TradeCPU on Urbana board]
  end
  subgraph CloudAI
    GEM[Gemini API]
    MUSE[Meta Model API]
  end
  UI -->|HTTP + session cookie| API
  API --> SVC
  API --> AI
  SVC --> BLK
  SVC --> COMP
  SVC --> PG
  SVC -->|UART LOAD_PROGRAM / TICK| FPGA
  AI --> GEM
  AI --> MUSE
  BLK --> COMP
  DBL --> PG
```

Early planning sketches (block categories and system shape):

![Framework overview](dev/planning/framework-overview.svg)

![Framework](dev/planning/framework.svg)

### Backtest sequence

```mermaid
sequenceDiagram
  participant User
  participant API as Backtest service
  participant Comp as Compiler
  participant DB as TimescaleDB
  participant FPGA as TradeCPU

  User->>API: POST /backtests
  API->>Comp: compile strategy (+ price exponents)
  Comp-->>API: manifest (words, warmup, symbols)
  API->>DB: load minute bars (range or latest N ticks)
  API->>API: pick int16 price scales per symbol
  API->>Comp: recompile with price_exponents
  API->>FPGA: LOAD_PROGRAM
  FPGA-->>API: EMIT_BALANCE (handshake)
  loop Each bar / tick
    API->>FPGA: TICK per BUF0..BUF4
    FPGA-->>API: DECISION_EVENT (0..n)
    FPGA-->>API: EMIT_BALANCE (tick ack)
  end
  API->>DB: store orders, balances, metrics
  API-->>User: report (return, drawdown, trades, source=fpga)
```

---

## How a strategy works

### Ports and the Start block

- **Exec ports** (chevrons) define execution order: one outgoing exec wire per block output.
- **Data ports** (circles) carry numeric values between blocks.
- The **Start** block runs once per tick. It sets starting balance, bar **resolution** (`1m` … `1d`), and legacy symbol slots on the document.
- **Get ticker** blocks assign symbols to hardware slots **BUF0–BUF4** (at most five stocks). Each slot has a 30-tick circular price history on the FPGA.

### Tick loop (compiler + hardware)

The compiler wraps your exec chain in a fixed program shape:

1. `SETBALANCE` + `EMITBALANCE` after load.
2. **Warm-up**: `(history − 1)` rounds of `UPDATEALLSTOCKBUFFERS` (no trading).
3. Each **tick**: `UPDATEALLSTOCKBUFFERS`, your strategy chain, then `GETBALANCE` / `EMITBALANCE` / jump back.

The host sends one **TICK** UART message per buffer per bar, then reads **DECISION_EVENT** messages until the next **EMIT_BALANCE**. See [TradeCPU hardware](#tradecpu-hardware).

### Hardware limits

| Limit | Value |
| --- | --- |
| Stock buffers | 5 (`BUF0`–`BUF4`) |
| Ticks per buffer | 30 |
| Variable slots | 15 (`VAR1`–`VAR15`) |
| Program memory | 512 words |

Prices are fixed-point: the host chooses a **price exponent** per symbol so scaled ticks fit in 16 bits. Balance is tracked in **cents** on the device.

### Document format (`m4ntis.strategy/v1`)

Strategies are JSON with a React Flow graph: nodes (`id`, `type`, `position`, `data.params`) and edges (`source` / `target` handles like `exec:out` and `data:a`).

```json
{
  "schema": "m4ntis.strategy/v1",
  "name": "Example",
  "flow": {
    "nodes": [
      {
        "id": "start",
        "type": "start",
        "position": { "x": 0, "y": 0 },
        "data": {
          "params": {
            "startingBalance": 100000,
            "resolution": "5m",
            "symbol0": "AAPL"
          }
        }
      },
      {
        "id": "t0",
        "type": "get_ticker",
        "position": { "x": 0, "y": 100 },
        "data": { "params": { "symbol": "AAPL", "buffer": 0 } }
      }
    ],
    "edges": []
  }
}
```

Full examples: [`dev/software/frontend/dev-sketchout/examples/`](dev/software/frontend/dev-sketchout/examples/).

---

## Block reference

Blocks the editor offers (palette groups). **Log** appears in the catalog but is **blocked**—the ISA has no logarithm. **Z-Score** is a **macro** (expanded to SMA, volatility, divide before compile).

| Category | Blocks |
| --- | --- |
| **Structure** | Start |
| **Market** | Get ticker, Sum of last N ticks, Price N ticks ago, Constant, Get Balance |
| **Variables** | Set Variable, Get Variable |
| **Math** | Add, Subtract, Multiply, Divide, Power, Square Root, Log (blocked) |
| **Control** | If / Else, For (range) |
| **Trade** | Buy, Sell |
| **Indicators** | SMA, Momentum, Volatility, Mean Reversion Bands, Z-Score |

Port and parameter details: [`src/backend/mantis/blocks/catalog.py`](src/backend/mantis/blocks/catalog.py) and [`src/frontend/src/blocks/catalog.ts`](src/frontend/src/blocks/catalog.ts).

---

## TradeCPU hardware

TradeCPU is a **single-cycle-class** processor (fetch → decode → execute → writeback in `control_unit.v`), running at **50 MHz** on the Urbana board. It is not a general-purpose CPU: registers, stock buffers, and opcodes exist for trading rules.

| Resource | Detail |
| --- | --- |
| GPRs | 8 × 32-bit (`R0`–`R7`) |
| Balance | 32-bit `BALANCE` (cents) |
| Variables | 15 × 16-bit slots |
| Stock buffers | 5 × 30-entry circular buffers |
| Opcodes | 27 implemented (+ 5 reserved) |

**Host UART (115200 8N1)**

| Message | Direction | Role |
| --- | --- | --- |
| `LOAD_PROGRAM` | Host → board | Upload up to 512 words without reflashing |
| `TICK` | Host → board | Stage one scaled price for a buffer |
| `DECISION_EVENT` | Board → host | Buy/sell/hold |
| `EMIT_BALANCE` | Board → host | Balance ack per tick / after load |

Authoritative bit-level spec: [`src/hardware/docs/tradecpu_full_specification.md`](src/hardware/docs/tradecpu_full_specification.md). RTL overview and build stages: [`src/hardware/README.md`](src/hardware/README.md).

**Board setup**

- Default serial port: **`COM4`** (Windows); set **`FPGA_SERIAL_PORT`** in `.env` on Linux/macOS (e.g. `/dev/ttyUSB0`).
- Baud: **`115200`** (`FPGA_BAUD`, default matches hardware).
- Bring-up scripts: [`src/hardware/python/`](src/hardware/python/).

Simulation: `bash src/hardware/scripts/run_sim.sh`.

---

## Repository layout

```text
.
├── README.md                 # This file (GitHub Pages site)
├── dev.sh                    # Start backend + frontend (current layout)
├── .env.example              # Environment template
├── src/
│   ├── backend/              # FastAPI app (python -m src.backend)
│   │   └── mantis/           # api, services, blocks, ai, db
│   ├── frontend/             # React + Vite editor and discussions
│   └── hardware/             # TradeCPU Verilog RTL, sim, docs
└── dev/
    ├── software/
    │   ├── compiler/         # Strategy → TradeCPU asm/hex (tradecpu package)
    │   └── database/         # Timescale loaders, SQL schemas
    ├── planning/             # Early diagrams and backlog notes
    └── scripts/dev.sh        # Legacy launcher (old software/ paths — use ./dev.sh)
```

Deeper docs: [`src/backend/README.md`](src/backend/README.md), [`src/frontend/README.md`](src/frontend/README.md), [`dev/software/compiler/README.md`](dev/software/compiler/README.md), [`dev/software/database/README.md`](dev/software/database/README.md).

---

## Getting started

### Prerequisites

- **Python 3.10+** with `pip`
- **Node.js 20+** and `npm` (for the frontend)
- **PostgreSQL** with TimescaleDB market data (Tiger connection) for symbols and backtests
- **TradeCPU board** on USB serial for FPGA backtests (optional for editor compile and AI)
- API keys: **`GEMINI_API_KEY`** and/or **`META_API_KEY`** for assistant, summaries, and analysis

### Environment (repo-root `.env`)

Copy [`.env.example`](.env.example) to `.env` and fill in values.

| Variable | Purpose |
| --- | --- |
| `TIGER_DB_PGHOST`, `TIGER_DB_PGPORT`, `TIGER_DB_PGDATABASE`, `TIGER_DB_PGUSER`, `TIGER_DB_PGPASSWORD`, `TIGER_DB_PGSSLMODE` | PostgreSQL / TimescaleDB for users, strategies, discussions, and `stock_minute_bars` |
| `GEMINI_API_KEY` | Google Gemini models for the assistant |
| `META_API_KEY` | Meta Muse Spark (assistant + discussion summaries) |
| `AI_PROVIDER`, `AI_MODEL` | Default assistant provider and model when the client omits them |
| `POST_SUMMARY_MODEL` | Muse model for thread summaries (default `muse-spark-1.3`) |
| `FPGA_SERIAL_PORT`, `FPGA_BAUD` | Serial port (default `COM4`) and baud (default `115200`) |
| `BACKTEST_TICKS`, `BACKTEST_MAX_TICKS` | Default bar count and cap after warm-up (defaults `500`, `20000`) |
| `BACKEND_PORT`, `FRONTEND_PORT` | API and Vite dev server (defaults `8001`, `8002`) |
| `VITE_API_URL` | Production frontend API base (dev uses Vite proxy to `BACKEND_PORT`) |
| `ALPACA_API_KEY`, `ALPACA_API_SECRET` | Used by database loaders (not the live app) |
| `CURSOR_API_KEY` | Optional; not required for Mantis runtime |

### Install and run

From the repository root:

```bash
python3 -m pip install -r src/backend/requirements.txt
cd src/frontend && npm install && cd ../..
```

**Backend** (port `BACKEND_PORT`, default 8001):

```bash
python3 -m src.backend
```

**Frontend** (port `FRONTEND_PORT`, default 8002; proxies API in dev):

```bash
cd src/frontend && npm run dev
```

**Both at once** (recommended):

```bash
./dev.sh
```

Do not use `dev/scripts/dev.sh`—it still points at `software/backend` and `software/frontend_prod`.

Production build: `cd src/frontend && npm run build`, then serve `dist/` with `VITE_API_URL` set to your API.

### Market data (optional, for backtests)

Loaders live under [`dev/software/database/`](dev/software/database/README.md) (`stock_minute_bars`, `stock_symbols`, `trading_days`, and related tables). The app expects minute bars for NASDAQ-100 names already present in Tiger.

---

## Testing

Commands below were run from the repo root on a machine with local Postgres (`postgresql://mantis:mantis@127.0.0.1:5432/mantis_test`). Start Postgres if needed: `sudo service postgresql start`.

**Backend** (install dev deps first: `pip install -r src/backend/requirements-dev.txt`):

```bash
MANTIS_TEST_DATABASE=postgresql://mantis:mantis@127.0.0.1:5432/mantis_test \
  python3 -m pytest src/backend/tests
```

Database tests recreate app tables in the test database. Some integration tests **mock** `market_data` and use the compiler’s **`FakeBoard`** instead of real hardware.

**Frontend**:

```bash
cd src/frontend
npm test
npm run build
```

**Compiler**:

```bash
python3 -m pytest dev/software/compiler/tests
```

Alternative from `dev/software/compiler`: `PYTHONPATH=/workspace python3 -m unittest discover -s tests`.

---

## API overview

Authenticated routes use the HttpOnly **`session`** cookie (register/login). Public: `/health`, `/symbols`, `/auth/register`, `/auth/login`.

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/symbols`, `/symbols/{symbol}` | Ticker search |
| `POST` | `/auth/register`, `/auth/login`, `/auth/logout` | Account session |
| `GET` | `/auth/me` | Current user |
| `GET`/`POST` | `/strategies`, `/strategies/{id}` | List, create, read, update |
| `POST` | `/strategies/{id}/copy` | Private copy |
| `GET`/`POST` | `/strategies/{id}/versions`, `.../revert` | History |
| `POST` | `/compile` | Strategy → asm/hex/manifest/diagnostics |
| `GET` | `/llm/models` | Assistant models and availability |
| `POST` | `/llm` | AI agent turn |
| `GET` | `/backtests/range` | Tradable date range for a strategy |
| `POST`/`GET` | `/backtests`, `/backtests/{id}` | Run on FPGA / fetch report |
| `POST` | `/backtests/{id}/analysis` | AI explanation of a run |
| `GET` | `/backtests/fpga` | Board connection status |
| `GET`/`POST` | `/discussions` | Feed and new post |
| `POST` | `/discussions/{id}/like`, `.../summary` | Like; Muse thread summary |

Full request/response notes: [`src/backend/README.md`](src/backend/README.md).

---

## AI features

| Feature | Behavior |
| --- | --- |
| **Strategy agent** | [`AgentHarness`](src/backend/mantis/ai/agent/README.md): JSON tool protocol (`add_block`, `connect`, `check_strategy`, …), validates after every edit, returns steps for the UI |
| **Models** | Picker lists Gemini 3.x (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview`) and Muse Spark (`muse-spark-1.3`, `muse-spark-1.2`) when keys are set |
| **Post summaries** | `POST /discussions/{id}/summary` caches Muse output until new replies |
| **Backtest analysis** | On-demand; sends strategy snapshot, metrics, sampled equity, and orders—answers are not cached |

Details: [`src/backend/mantis/ai/README.md`](src/backend/mantis/ai/README.md).

---

## Roadmap and known limitations

- **No software backtest fallback**—without the FPGA, `POST /backtests` returns 503; only one run can use the board at a time (409 if busy).
- **Test database** has app tables but not full Timescale market-data hypertables; tests patch `market_data` queries and drive **`FakeBoard`** for FPGA paths.
- **Log block** cannot compile; several spec opcodes (`CMP_GTE`, `AND`, …) are intentionally not emitted because current RTL does not implement them.
- **Physical bring-up** on the Urbana board is ongoing; RTL is verified in simulation and Vivado timing checkpoints ([`src/hardware/checkpoints/`](src/hardware/checkpoints/README.md)).
- Early [`dev/planning/README.md`](dev/planning/README.md) items are largely superseded by the shipped API and UI.

---

## Further reading

| Topic | Location |
| --- | --- |
| Backend modules | [`src/backend/README.md`](src/backend/README.md) |
| Frontend screens | [`src/frontend/README.md`](src/frontend/README.md) |
| Editor UI | [`src/frontend/src/features/editor/README.md`](src/frontend/src/features/editor/README.md) |
| Compiler CLI and hwtest | [`dev/software/compiler/README.md`](dev/software/compiler/README.md) |
| Database loaders | [`dev/software/database/README.md`](dev/software/database/README.md) |
| TradeCPU ISA | [`src/hardware/docs/tradecpu_full_specification.md`](src/hardware/docs/tradecpu_full_specification.md) |

---

**Team:** Georgia Tech — GT Hacks Fall '26.
