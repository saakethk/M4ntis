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

## AI assistant client (not wired to any endpoint yet)
`helpers/ai_agent.py` gives one `AIAgent` class for every model provider, all sharing the system
prompt in `helpers/prompts/assistant_system.md`.

```python
from helpers.ai_agent import AIAgent, Message

agent = AIAgent.from_env()                        # AI_PROVIDER, AI_MODEL (+ AI_BASE_URL) in .env
agent = AIAgent("gemini", model="<model id>")     # or pick explicitly; key from GEMINI_API_KEY
reply = agent.chat("How do I build an SMA crossover?")
reply = agent.chat([Message("user", "..."), Message("assistant", "..."), Message("user", "...")])
reply.text, reply.input_tokens, reply.output_tokens, reply.finish_reason
```

| `AI_PROVIDER` | API key variable | Endpoint |
| --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | OpenAI Chat Completions |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic Messages |
| `gemini` | `GEMINI_API_KEY` | Gemini `generateContent` |
| `meta` | `META_API_KEY` | Llama API, OpenAI-compatible endpoint |
| `openai_compatible` | `AI_API_KEY` (optional) | Any OpenAI-style server at `AI_BASE_URL`, e.g. Ollama or vLLM |

Errors raise `AIConfigError` (bad setup) or `AIProviderError` (the API refused or failed, with
`.status`). Rate limits and 5xx responses are retried twice. To add another vendor, subclass
`Provider` and register it in `PROVIDERS`.

## To Run
1. cd software/backend
2. python main.py
   The listen port comes from BACKEND_PORT in the repo-root .env (default 8001). The frontend dev server uses FRONTEND_PORT (default 8002).
Both processes can be started with ./scripts/dev.sh.
