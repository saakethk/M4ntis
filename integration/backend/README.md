# Mantis backend

FastAPI server behind the Mantis web app. Run it with `python main.py` from this folder
(port `BACKEND_PORT`, default 8001); settings come from the repo-root `.env`.
See the [integration README](../README.md) for setup and the full system picture.

## Layout

```
main.py                 entry point: builds the app and runs uvicorn
mantis/
  config.py             repo paths and .env loading (env, env_port)
  errors.py             domain errors; each carries its HTTP status
  api/                  HTTP layer                        -> api/README.md
  services/             domain logic and SQL              -> services/README.md
  blocks/               block catalog, canvas, macros     -> blocks/README.md
  ai/                   chat client, agent, summaries     -> ai/README.md
  db/                   connections and schema bootstrap  -> db/README.md
tests/                  pytest suite
```

Dependencies point one way: `api` → `services` / `ai` → `blocks` / `db`. Services never
import FastAPI; they raise `mantis.errors` and the app maps them to responses.

## Endpoints

All routes except `/health`, `/symbols`, and `/auth/register|login` need the `session` cookie.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Liveness check |
| `GET /symbols?q=&limit=` · `GET /symbols/{symbol}` | Ticker and company search |
| `POST /auth/register` · `POST /auth/login` | `{email, password}`; sets a 14-day HttpOnly `session` cookie |
| `POST /auth/logout` · `GET /auth/me` | End the session · current user |
| `POST /strategies` · `GET /strategies` | Create (`{name, document, ir?, visibility?}`) · list your strategies, each with `last_backtest` (`{id, created_at, source, return_pct, max_drawdown_pct, num_trades}` or null) |
| `GET /strategies/{id}` | A strategy you own or that is public, with `owned` |
| `PUT /strategies/{id}` | Owner updates any of `name`, `document`, `ir`, `visibility` |
| `POST /strategies/{id}/copy` | Private copy of a strategy you can view |
| `GET /strategies/{id}/versions` · `POST .../versions/{vid}/revert` | Owner's saved versions · restore one |
| `POST /compile` | Compile a `m4ntis.strategy/v1` document or `{strategy_id?, document?, price_exponents?}`. 200: `{ok, asm, hex, manifest, diagnostics}`; rejected: 400 `{ok: false, detail, diagnostics}` |
| `GET /llm/models` | Assistant models, each with `available` (API key configured), and the default |
| `POST /llm` | `{prompt, graph?, provider?, model?, history?}` → `{reply, graph, steps, model}`; `graph` is the edited canvas or `null` |
| `POST /backtests` · `GET /backtests/{id}` | `{user_id, strategy_id}` → run on the TradeCPU FPGA over the latest `BACKTEST_TICKS` bars from TimescaleDB · report with metrics and `source` (`fpga`, or `sample` for old runs). No board: 503; board in use: 409 |
| `POST /backtests/{id}/analysis` | `{provider?, model?, question?}` → `{id, analysis, model}`: the chosen model explains a run you can view and suggests changes; not cached |
| `GET /backtests/fpga` | `{connected, port, busy, detail}` for the board at `FPGA_SERIAL_PORT`, without opening it |
| `GET /discussions` · `POST /discussions` | Feed (with cached summaries) · post `{body, strategy_id?, parent_id?}`; attaching your private strategy publishes it |
| `POST /discussions/{id}/like` | Toggle your like |
| `POST /discussions/{id}/summary` | `{refresh?}` → Muse-written thread summary, cached until new replies arrive |

Errors are `{"detail": "..."}` with 400 (bad input), 401, 403, 404, 409, 422
(schema validation), 502 (AI provider failed), or 503 (database, AI, or FPGA not available).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                                   # database tests skip
MANTIS_TEST_DATABASE=postgresql://u:p@127.0.0.1:5432/mantis_test python -m pytest
```

The database tests drop and recreate the app's tables, so point them at a throwaway database.
