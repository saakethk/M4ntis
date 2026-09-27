"""Pretend strategy assistant.

Nothing is sent to a model. A prompt that asks for a trade becomes a small
SMA crossover using Start for the bar size and Get ticker for the stock.
"""

from __future__ import annotations

import re

MAX_PROMPT_LENGTH = 2000

HELP = (
    "Start only chooses how often the strategy runs: every 1 minute, 5 minutes, "
    "15 minutes, 30 minutes, 1 hour, or 1 day. Add a Get ticker block and search "
    "for the stock, such as AAPL. Compare a fast average with a slow average, "
    "buy when the fast one is higher, and sell when it is lower."
)

_RESOLUTIONS = (
    ("15 minutes", "15m"),
    ("15 minute", "15m"),
    ("30 minutes", "30m"),
    ("30 minute", "30m"),
    ("1 minute", "1m"),
    ("5 minutes", "5m"),
    ("5 minute", "5m"),
    ("1 hour", "1h"),
    ("1 day", "1d"),
    ("15 min", "15m"),
    ("30 min", "30m"),
    ("1 min", "1m"),
    ("5 min", "5m"),
    ("hourly", "1h"),
    ("daily", "1d"),
)

_EVERY = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "1d": "1 day",
}

_NAMES = {
    "APPLE": "AAPL",
    "MICROSOFT": "MSFT",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "AMAZON": "AMZN",
    "GOOGLE": "GOOGL",
    "META": "META",
}

_INTENT = ("buy", "sell", "sma", "average", "crossover", "ticker", "aapl", "apple")


def dummy_reply(prompt: str) -> dict[str, object]:
    """Return a fixed-style reply, plus a program when the prompt asks for a trade."""
    text = prompt.strip()
    if not text:
        raise ValueError("Prompt is required")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt is too long")
    program = _program(text)
    if program is None:
        return {"reply": HELP, "dummy": True, "program": None}
    reply = (
        f"Every {_EVERY[str(program['resolution'])]}, Get ticker {program['symbol']}. "
        f"If the {program['fast']}-bar average is above the {program['slow']}-bar average, "
        f"buy {program['quantity']}; otherwise sell {program['quantity']}."
    )
    return {"reply": reply, "dummy": True, "program": program}


def _program(text: str) -> dict[str, object] | None:
    lower = text.lower()
    if not any(word in lower for word in _INTENT):
        return None
    scanned = lower
    quantity_match = re.search(r"\b(?:buy|sell|quantity|shares?)\s+(\d{1,5})\b", scanned)
    quantity = int(quantity_match.group(1)) if quantity_match else 10
    quantity = min(max(quantity, 1), 32767)
    if quantity_match:
        scanned = scanned.replace(quantity_match.group(0), " ", 1)
    resolution = _resolution(scanned)
    for phrase, value in _RESOLUTIONS:
        if value == resolution and phrase in scanned:
            scanned = scanned.replace(phrase, " ", 1)
            break
    windows = [int(n) for n in re.findall(r"\b\d{1,2}\b", scanned) if 1 <= int(n) <= 30]
    fast = windows[0] if windows else 10
    slow = windows[1] if len(windows) > 1 else 30
    if slow <= fast:
        slow = min(30, fast + 1)
    if slow <= fast:
        fast = max(1, slow - 1)
    return {
        "resolution": resolution,
        "symbol": _symbol(text),
        "fast": fast,
        "slow": slow,
        "quantity": quantity,
    }


def _resolution(lower: str) -> str:
    for phrase, value in _RESOLUTIONS:
        if phrase in lower:
            return value
    return "5m"


def _symbol(text: str) -> str:
    upper = text.upper()
    for name, ticker in _NAMES.items():
        if name in upper:
            return ticker
    for token in re.findall(r"\b[A-Z]{2,5}\b", text):
        if token not in {"SMA", "BUY", "SELL", "EVERY", "HOUR", "DAY"}:
            return token
    return "AAPL"
