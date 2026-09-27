"""Pretend strategy assistant.

Nothing is sent to a model. The reply is a fixed suggestion.
"""

from __future__ import annotations

MAX_PROMPT_LENGTH = 2000

DUMMY_REPLY = (
    "Try a simple crossover: compare a fast price with a slow price, "
    "buy when the fast price is higher, and sell when it is lower."
)


def dummy_reply(prompt: str) -> dict[str, object]:
    """Return a fixed assistant reply for a non-empty prompt."""
    text = prompt.strip()
    if not text:
        raise ValueError("Prompt is required")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt is too long")
    return {"reply": DUMMY_REPLY, "dummy": True}
