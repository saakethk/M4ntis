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
            record = conn.execute(
                _INSERT_POST,
                (user_id, cleaned, stored_strategy_id, parent_id),
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


def _connect() -> psycopg.Connection:
    return connect()
