# Backend Server
This is the code to expose the backend code like the FPGA interface and such to the frontend website.

## Endpoints
- /symbols?q=[query]&limit=[limit]
  - query: user can search either a symbol or stock
  - limit: the max number of results to return
  - result: output a list of the relevant results
- POST /auth/register and POST /auth/login with `{ "email", "password" }`
  - sets an HttpOnly `session` cookie for 14 days
- POST /auth/logout clears that cookie
- GET /auth/me returns the signed-in user
- POST /strategies with `{ "name", "document", "ir"?, "visibility"? }` saves a strategy for the signed-in user. `visibility` is `private` or `public` (default `private`). Returns `{ "id", "name", "visibility", "updated_at" }`
- GET /strategies lists strategies the signed-in user owns (`id`, `name`, `visibility`, `updated_at`)
- GET /strategies/{id} returns `document` and `ir` when the user owns the strategy or it is public, plus `owned`
- PUT /strategies/{id} lets the owner update `name`, `document`, `ir`, or `visibility` (`private` or `public`) and returns `{ "id", "name", "visibility", "updated_at" }`
- POST /strategies/{id}/copy creates a private copy owned by the signed-in user when they can view the original
- POST /compile compiles a strategy for the signed-in user. The body is an `m4ntis.strategy/v1` document, an `m4ntis.strategy-ir/v1` object, or `{ "strategy_id"?, "document"? }`. A strategy id is compiled only when that user can view it. Success returns the compiler JSON (`ok`, `asm`, `hex`, `manifest`, `diagnostics`). A document that does not compile returns 400 with the compiler message.
- POST /backtests with `{ "user_id", "strategy_id" }` stores a dummy backtest for the signed-in user. `user_id` must be that user. It snapshots the strategy and writes sample orders and balances. Nothing is run against market data.
- POST /discussions with `{ "body", "strategy_id"?, "parent_id"? }` creates a post for the signed-in user. Returns `{ "id", "strategy_id", "strategy_made_public" }`. If the author owns `strategy_id` and it is private, the strategy becomes `public` (view-only) and `strategy_made_public` is true. A non-owner cannot publish someone else's private strategy.

## To Run
1. cd software/backend
2. python main.py
   The listen port comes from BACKEND_PORT in the repo-root .env (default 8001). The frontend dev server uses FRONTEND_PORT (default 8002).
Both processes can be started with ./scripts/dev.sh.
