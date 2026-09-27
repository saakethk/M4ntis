# AI features

```
providers.py   one adapter per vendor API (Gemini, Meta, OpenAI, Anthropic, OpenAI-compatible)
client.py      ChatClient: same request and response for every provider, retries, config errors
models.py      the models the product offers, defaults, and validation of the user's choice
prompts/       prompt files (assistant persona, agent protocol, post summary)
agent/         tool-using harness that edits block graphs        -> agent/README.md
assistant.py   POST /llm: runs the agent with the chosen model and the compiler as checker
summaries.py   thread summaries written by Meta Muse Spark
```

## Models

| Provider | Key | Models offered | Endpoint |
| --- | --- | --- | --- |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` | Gemini `generateContent` |
| `meta` | `META_API_KEY` | `muse-spark-1.3`, `muse-spark-1.2` | Meta Model API, `https://api.meta.ai/v1/chat/completions` |

`openai`, `anthropic`, and `openai_compatible` (any OpenAI-style server at
`AI_BASE_URL`, e.g. Ollama) also work as the environment default through
`AI_PROVIDER` and `AI_MODEL`, but are not listed in the picker. `<PROVIDER>_BASE_URL`
(for example `META_BASE_URL`) points one provider at a gateway or proxy.

Gemini 3 and Muse Spark are reasoning models tuned for their default sampling, so
their adapters never send `temperature`. Muse uses `max_completion_tokens`.

To offer a new model, add it to `ASSISTANT_MODELS` in `models.py`; the editor's
picker reads that list from `GET /llm/models`. To add a vendor, subclass `Provider`
in `providers.py` and register it in `PROVIDERS`.

## Post summaries

`POST /discussions/{id}/summary` sends the post, the attached strategy's block counts,
and every reply to Muse Spark (`POST_SUMMARY_MODEL`, default `muse-spark-1.3`) with
`prompts/post_summary.md`. The result is stored on the post with the reply count it
saw; it is reused until a new reply arrives or the user asks to regenerate.
