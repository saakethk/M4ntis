"""AI summaries of discussion threads, written by Meta's Muse Spark.

:func:`summarize_thread` is the ``Summarizer`` that
:func:`mantis.services.discussions.summarize_post` calls when a summary is
missing or stale. It needs ``META_API_KEY``; ``POST_SUMMARY_MODEL`` may choose
another Muse model.
"""

from __future__ import annotations

from src.backend.mantis.ai.client import ChatClient
from src.backend.mantis.ai.models import SUMMARY_PROVIDER, summary_model
from src.backend.mantis.ai.prompts import load_prompt
from src.backend.mantis.ai.providers import AIConfigError, AIProviderError
from src.backend.mantis.errors import ServiceUnavailable, UpstreamFailed
from src.backend.mantis.services.discussions import Thread

MAX_THREAD_CHARS = 12_000


def summarize_thread(thread: Thread, client: ChatClient | None = None) -> tuple[str, str]:
    """Return ``(summary, model id)`` for a thread. A passed-in client is left open."""
    try:
        active = client or ChatClient(SUMMARY_PROVIDER, summary_model())
        try:
            response = active.chat(thread_text(thread), system=load_prompt("post_summary.md"), max_tokens=1024)
        finally:
            if client is None:
                active.close()
    except AIConfigError as exc:
        raise ServiceUnavailable(f"Post summaries need Meta Muse. {exc}") from exc
    except AIProviderError as exc:
        raise UpstreamFailed("Summary service is unavailable") from exc
    summary = " ".join(response.text.split())
    if not summary:
        raise UpstreamFailed("Summary service returned an empty summary")
    return summary, active.model


def thread_text(thread: Thread) -> str:
    """The thread as plain text, trimmed from the end so the original post always fits."""
    lines = [f"Original post by {_name(thread.post.author)}:\n{thread.post.body}"]
    if thread.strategy_name:
        blocks = ", ".join(f"{count} x {kind}" for kind, count in sorted(thread.strategy_blocks.items()))
        lines.append(f"Attached strategy: {thread.strategy_name}" + (f" (blocks: {blocks})" if blocks else ""))
    for index, reply in enumerate(thread.replies, start=1):
        lines.append(f"Reply {index} by {_name(reply.author)}:\n{reply.body}")
    text = "\n\n".join(lines)
    return text if len(text) <= MAX_THREAD_CHARS else text[:MAX_THREAD_CHARS] + "\n\n[thread truncated]"


def _name(email: str) -> str:
    return email.split("@", 1)[0] or "someone"
