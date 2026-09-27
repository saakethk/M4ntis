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