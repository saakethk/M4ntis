"""Strategy assistant backed by the configured model provider.

POST /llm sends the user's prompt to AIAgent (AI_PROVIDER / AI_MODEL). The reply
is the model's explanation. When the user asks for a one-stock SMA crossover,
the model also returns a program the editor can place on the canvas.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from helpers.ai_agent import AIAgent, AIConfigError, AIProviderError, load_system_prompt

MAX_PROMPT_LENGTH = 2000
RESOLUTIONS = ("1m", "5m", "15m", "30m", "1h", "1d")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,7}$")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

# Appended to the shared assistant prompt. The editor can only apply an SMA
# crossover, so a program is included only for that shape.
APPENDIX = """
## Canvas program

The editor can place one strategy on the canvas from your reply: a single-stock SMA crossover. Start sets the resolution. Get ticker holds the stock. A fast SMA and a slow SMA feed an If block. Then buys, Else sells the same quantity.

When the user asks for that crossover, end your reply with one fenced JSON block and nothing after it:

```json
{"program": {"resolution": "5m", "symbol": "AAPL", "fast": 10, "slow": 30, "quantity": 10}}
```

Use only these values:
- resolution: 1m, 5m, 15m, 30m, 1h, or 1d
- symbol: one ticker
- fast and slow: whole numbers from 1 to 30, with slow greater than fast
- quantity: a whole number of shares from 1 to 32767

The prose before the fence is what the user reads. Explain the rule and the connections in that prose.

For any other request, including mean reversion, several stocks, or a general question, do not include a program block. Describe the blocks in prose instead.
""".strip()


def system_prompt() -> str:
    return f"{load_system_prompt()}\n\n{APPENDIX}"


def ask(prompt: str, *, complete: Callable[[str], str] | None = None) -> dict[str, object]:
    """Send one prompt to the model and return reply text plus an optional program."""
    text = prompt.strip()
    if not text:
        raise ValueError("Prompt is required")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt is too long")
    raw = (complete or _complete)(text)
    reply, program = _split(raw)
    return {"reply": reply, "dummy": False, "program": program}


def _complete(prompt: str) -> str:
    with AIAgent.from_env() as agent:
        response = agent.chat(prompt, system_prompt=system_prompt(), temperature=0.2, max_tokens=1500)
    if not response.text.strip():
        raise AIProviderError(response.provider, "empty response")
    return response.text


def _split(text: str) -> tuple[str, dict[str, object] | None]:
    stripped = text.strip()
    if not stripped:
        raise AIProviderError("assistant", "empty response")
    whole = _json_object(stripped)
    if whole is not None and isinstance(whole.get("reply"), str) and whole["reply"].strip():
        return whole["reply"].strip(), _program(whole.get("program"))
    program: dict[str, object] | None = None
    reply = stripped
    for match in _FENCE.finditer(stripped):
        payload = _json_object(match.group(1))
        if payload is None or "program" not in payload:
            continue
        program = _program(payload.get("program"))
        reply = f"{stripped[: match.start()]}{stripped[match.end() :]}".strip()
    if program is not None and not reply:
        reply = "Here is an SMA crossover you can apply to the canvas."
    return reply, program


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _program(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    resolution = value.get("resolution")
    symbol = value.get("symbol")
    fast = _whole(value.get("fast"))
    slow = _whole(value.get("slow"))
    quantity = _whole(value.get("quantity"))
    if resolution not in RESOLUTIONS or not isinstance(symbol, str):
        return None
    ticker = symbol.strip().upper()
    if _SYMBOL.fullmatch(ticker) is None or fast is None or slow is None or quantity is None:
        return None
    if not (1 <= fast <= 30 and 1 <= slow <= 30 and slow > fast):
        return None
    if not 1 <= quantity <= 32767:
        return None
    return {
        "resolution": resolution,
        "symbol": ticker,
        "fast": fast,
        "slow": slow,
        "quantity": quantity,
    }


def _whole(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


__all__ = ["AIConfigError", "AIProviderError", "MAX_PROMPT_LENGTH", "ask", "system_prompt"]
