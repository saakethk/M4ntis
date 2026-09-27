"""Discussion posts.

Pointing a post at a strategy publishes that strategy for viewing when the
author owns it and it is still private. A non-owner cannot publish someone
else's private strategy, and this module never changes visibility for them.
"""

from __future__ import annotations

from typing import Any

import psycopg

from helpers.db import connect
from helpers.strategies import PRIVATE, PUBLIC, StrategyForbidden, StrategyNotFound


class PostNotFound(Exception):
    pass

_SELECT_STRATEGY = """
SELECT id, user_id, visibility
FROM strategies
WHERE id = %s
"""

_PUBLISH_STRATEGY = """
UPDATE strategies
SET visibility = 'public', updated_at = now()
WHERE id = %s AND user_id = %s AND visibility = 'private'
RETURNING id
"""

_INSERT_POST = """
INSERT INTO discussion_posts (user_id, body, strategy_id, parent_id)
VALUES (%s, %s, %s, %s)
RETURNING id
"""


def clean_body(body: object) -> str:
    if not isinstance(body, str):
        raise ValueError("Post body is required")
    cleaned = body.strip()
    if not cleaned:
        raise ValueError("Post body is required")
    return cleaned


def create_post(
    user_id: int,
    body: object,
    strategy_id: int | None = None,
    parent_id: int | None = None,
) -> dict[str, Any]:
    """Insert a post. Returns id, strategy_id, and strategy_made_public.

    strategy_made_public is true only when this call changed the strategy
    from private to public.
    """
    cleaned = clean_body(body)
    conn = _connect()
    try:
        with conn.transaction():
            made_public, stored_strategy_id = _attach_strategy(conn, user_id, strategy_id)
            stored_parent_id = _require_parent(conn, parent_id)
            record = conn.execute(
                _INSERT_POST,
                (user_id, cleaned, stored_strategy_id, stored_parent_id),
            ).fetchone()
        return {
            "id": int(record[0]),
            "strategy_id": stored_strategy_id,
            "strategy_made_public": made_public,
        }
    finally:
        conn.close()


def _attach_strategy(
    conn: psycopg.Connection,
    user_id: int,
    strategy_id: int | None,
) -> tuple[bool, int | None]:
    if strategy_id is None:
        return False, None
    stored_strategy_id = int(strategy_id)
    row = conn.execute(_SELECT_STRATEGY, (stored_strategy_id,)).fetchone()
    if row is None:
        raise StrategyNotFound()
    owner_id = int(row[1])
    visibility = str(row[2])
    if owner_id != user_id and visibility != PUBLIC:
        raise StrategyForbidden()
    if owner_id != user_id or visibility != PRIVATE:
        return False, stored_strategy_id
    updated = conn.execute(
        _PUBLISH_STRATEGY,
        (stored_strategy_id, user_id),
    ).fetchone()
    return updated is not None, stored_strategy_id


def _require_parent(conn: psycopg.Connection, parent_id: int | None) -> int | None:
    if parent_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM discussion_posts WHERE id = %s",
        (int(parent_id),),
    ).fetchone()
    if row is None:
        raise PostNotFound()
    return int(parent_id)


def list_posts(user_id: int) -> list[dict[str, Any]]:
    """Every post, oldest first, with whether this user liked it."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.user_id, u.email, p.body, p.strategy_id, p.parent_id,
                   p.likes_count, p.created_at,
                   EXISTS (
                       SELECT 1 FROM discussion_likes l
                       WHERE l.post_id = p.id AND l.user_id = %s
                   )
            FROM discussion_posts p
            JOIN users u ON u.id = p.user_id
            ORDER BY p.created_at, p.id
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_public_post(row) for row in rows]


def toggle_like(user_id: int, post_id: int) -> dict[str, Any]:
    """Like a post, or remove the like if it is already there."""
    conn = _connect()
    try:
        with conn.transaction():
            post = conn.execute(
                "SELECT likes_count FROM discussion_posts WHERE id = %s",
                (post_id,),
            ).fetchone()
            if post is None:
                raise PostNotFound()
            existing = conn.execute(
                """
                SELECT 1 FROM discussion_likes
                WHERE post_id = %s AND user_id = %s
                """,
                (post_id, user_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO discussion_likes (post_id, user_id) VALUES (%s, %s)",
                    (post_id, user_id),
                )
                liked = True
                delta = 1
            else:
                conn.execute(
                    "DELETE FROM discussion_likes WHERE post_id = %s AND user_id = %s",
                    (post_id, user_id),
                )
                liked = False
                delta = -1
            updated = conn.execute(
                """
                UPDATE discussion_posts
                SET likes_count = GREATEST(likes_count + %s, 0)
                WHERE id = %s
                RETURNING likes_count
                """,
                (delta, post_id),
            ).fetchone()
        return {"id": post_id, "likes_count": int(updated[0]), "liked": liked}
    finally:
        conn.close()


def _public_post(row: tuple[Any, ...]) -> dict[str, Any]:
    created = row[7]
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "author": str(row[2]),
        "body": str(row[3]),
        "strategy_id": None if row[4] is None else int(row[4]),
        "parent_id": None if row[5] is None else int(row[5]),
        "likes_count": int(row[6]),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
        "liked": bool(row[8]),
    }


def _connect() -> psycopg.Connection:
    return connect()
