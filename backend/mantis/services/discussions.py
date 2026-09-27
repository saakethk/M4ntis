"""Discussion posts, replies, likes, and cached AI thread summaries.

Attaching a strategy to a post publishes it: when the author owns the strategy and
it is still private, it becomes public (view-only for everyone else). Someone who
does not own a private strategy cannot attach it.

A summary covers one post and every reply beneath it. It is generated on request,
stored on the post, and regenerated only when new replies arrive or the caller
asks for a refresh.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from backend.mantis import db
from backend.mantis.errors import Forbidden, InvalidInput, NotFound
from backend.mantis.services.strategies import PRIVATE, PUBLIC, StrategyNotFound

MAX_BODY = 4000


class PostNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("Post not found")


@dataclass(frozen=True)
class ThreadPost:
    author: str
    body: str


@dataclass(frozen=True)
class Thread:
    """What the summarizer reads: the post, its shared strategy, and its replies in order."""

    post: ThreadPost
    strategy_name: str | None = None
    strategy_blocks: dict[str, int] = field(default_factory=dict)
    replies: tuple[ThreadPost, ...] = ()


Summarizer = Callable[[Thread], tuple[str, str]]
"""Returns ``(summary text, model id)`` for a thread."""


def clean_body(body: object) -> str:
    if not isinstance(body, str) or not body.strip():
        raise InvalidInput("Post body is required")
    if len(body) > MAX_BODY:
        raise InvalidInput(f"Post body must be at most {MAX_BODY} characters")
    return body.strip()


def create_post(
    user_id: int,
    body: object,
    strategy_id: int | None = None,
    parent_id: int | None = None,
) -> dict[str, Any]:
    """Insert a post. ``strategy_made_public`` is true only if this call published the strategy."""
    cleaned = clean_body(body)
    with db.session() as conn, conn.transaction():
        made_public = _attach_strategy(conn, user_id, strategy_id)
        if parent_id is not None and not _exists(conn, parent_id):
            raise PostNotFound()
        post_id = conn.execute(
            """
            INSERT INTO discussion_posts (user_id, body, strategy_id, parent_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (user_id, cleaned, strategy_id, parent_id),
        ).fetchone()[0]
    return {"id": int(post_id), "strategy_id": strategy_id, "strategy_made_public": made_public}


def list_posts(user_id: int) -> list[dict[str, Any]]:
    """Every post, newest first, with whether this user liked it and any cached summary."""
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.user_id, u.email, p.body, p.strategy_id, s.name,
                   p.parent_id, p.likes_count, p.created_at,
                   EXISTS (
                       SELECT 1 FROM discussion_likes l
                       WHERE l.post_id = p.id AND l.user_id = %s
                   ),
                   p.ai_summary, p.ai_summary_model, p.ai_summary_reply_count
            FROM discussion_posts p
            JOIN users u ON u.id = p.user_id
            LEFT JOIN strategies s ON s.id = p.strategy_id
            ORDER BY p.created_at DESC, p.id DESC
            """,
            (user_id,),
        ).fetchall()
    reply_counts = _descendant_counts([(int(r[0]), r[6]) for r in rows])
    return [_post_to_api(row, reply_counts.get(int(row[0]), 0)) for row in rows]


def toggle_like(user_id: int, post_id: int) -> dict[str, Any]:
    """Like a post, or remove the like if the user already liked it."""
    with db.session() as conn, conn.transaction():
        if not _exists(conn, post_id):
            raise PostNotFound()
        removed = conn.execute(
            "DELETE FROM discussion_likes WHERE post_id = %s AND user_id = %s RETURNING 1",
            (post_id, user_id),
        ).fetchone()
        if removed is None:
            conn.execute(
                "INSERT INTO discussion_likes (post_id, user_id) VALUES (%s, %s)",
                (post_id, user_id),
            )
        likes = conn.execute(
            """
            UPDATE discussion_posts SET likes_count = GREATEST(likes_count + %s, 0)
            WHERE id = %s RETURNING likes_count
            """,
            (-1 if removed else 1, post_id),
        ).fetchone()[0]
    return {"id": post_id, "likes_count": int(likes), "liked": removed is None}


def summarize_post(post_id: int, summarizer: Summarizer, *, refresh: bool = False) -> dict[str, Any]:
    """The thread summary for a post, generating and caching it when missing or stale."""
    with db.session() as conn:
        thread, cached = _load_thread(conn, post_id)
    reply_count = len(thread.replies)
    if cached is not None and not refresh and cached["reply_count"] == reply_count:
        return {"id": post_id, "summary": cached["text"], "model": cached["model"], "cached": True}
    text, model = summarizer(thread)
    with db.session() as conn:
        conn.execute(
            """
            UPDATE discussion_posts
            SET ai_summary = %s, ai_summary_model = %s, ai_summary_reply_count = %s, ai_summary_at = now()
            WHERE id = %s
            """,
            (text, model, reply_count, post_id),
        )
    return {"id": post_id, "summary": text, "model": model, "cached": False}


def _attach_strategy(conn: psycopg.Connection, user_id: int, strategy_id: int | None) -> bool:
    if strategy_id is None:
        return False
    row = conn.execute("SELECT user_id, visibility FROM strategies WHERE id = %s", (strategy_id,)).fetchone()
    if row is None:
        raise StrategyNotFound()
    owner_id, visibility = int(row[0]), str(row[1])
    if owner_id != user_id and visibility != PUBLIC:
        raise Forbidden("Only the owner can publish a private strategy")
    if owner_id != user_id or visibility != PRIVATE:
        return False
    published = conn.execute(
        """
        UPDATE strategies SET visibility = 'public', updated_at = now()
        WHERE id = %s AND user_id = %s AND visibility = 'private'
        RETURNING id
        """,
        (strategy_id, user_id),
    ).fetchone()
    return published is not None


def _exists(conn: psycopg.Connection, post_id: int) -> bool:
    return conn.execute("SELECT 1 FROM discussion_posts WHERE id = %s", (post_id,)).fetchone() is not None


def _load_thread(conn: psycopg.Connection, post_id: int) -> tuple[Thread, dict[str, Any] | None]:
    root = conn.execute(
        """
        SELECT u.email, p.body, s.name, s.document,
               p.ai_summary, p.ai_summary_model, p.ai_summary_reply_count
        FROM discussion_posts p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN strategies s ON s.id = p.strategy_id
        WHERE p.id = %s
        """,
        (post_id,),
    ).fetchone()
    if root is None:
        raise PostNotFound()
    replies = conn.execute(
        """
        WITH RECURSIVE thread AS (
            SELECT id, user_id, body, created_at FROM discussion_posts WHERE parent_id = %s
            UNION ALL
            SELECT p.id, p.user_id, p.body, p.created_at
            FROM discussion_posts p JOIN thread t ON p.parent_id = t.id
        )
        SELECT u.email, thread.body FROM thread
        JOIN users u ON u.id = thread.user_id
        ORDER BY thread.created_at, thread.id
        """,
        (post_id,),
    ).fetchall()
    thread = Thread(
        post=ThreadPost(str(root[0]), str(root[1])),
        strategy_name=None if root[2] is None else str(root[2]),
        strategy_blocks=_block_counts(root[3]),
        replies=tuple(ThreadPost(str(r[0]), str(r[1])) for r in replies),
    )
    cached = None
    if root[4]:
        cached = {"text": str(root[4]), "model": str(root[5] or ""), "reply_count": root[6]}
    return thread, cached


def _block_counts(document: Any) -> dict[str, int]:
    """Block types in a strategy document, e.g. ``{"sma": 2, "buy": 1}``."""
    if not isinstance(document, dict):
        return {}
    nodes = (document.get("flow") or {}).get("nodes") or []
    return dict(Counter(str(node.get("type")) for node in nodes if isinstance(node, dict)))


def _descendant_counts(posts: list[tuple[int, int | None]]) -> dict[int, int]:
    """Number of replies at any depth beneath each post."""
    parent_of = {post_id: parent for post_id, parent in posts}
    counts: dict[int, int] = {}
    for post_id in parent_of:
        parent = parent_of[post_id]
        seen: set[int] = set()
        while parent is not None and parent not in seen:
            seen.add(parent)
            counts[parent] = counts.get(parent, 0) + 1
            parent = parent_of.get(parent)
    return counts


def _post_to_api(row: tuple[Any, ...], reply_count: int) -> dict[str, Any]:
    summary = None
    if row[10]:
        summary = {"text": str(row[10]), "model": str(row[11] or ""), "stale": row[12] != reply_count}
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "author": str(row[2]),
        "body": str(row[3]),
        "strategy_id": None if row[4] is None else int(row[4]),
        "strategy_name": None if row[5] is None else str(row[5]),
        "parent_id": None if row[6] is None else int(row[6]),
        "likes_count": int(row[7]),
        "created_at": row[8].isoformat(),
        "liked": bool(row[9]),
        "summary": summary,
    }
