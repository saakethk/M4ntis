"""Saved strategies with private or public visibility.

Public means any signed-in user can view the document. Only the owner can
update or delete the row. Another user copies a strategy into a new private
row they own; the original row is left unchanged.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from helpers.db import connect

PRIVATE = "private"
PUBLIC = "public"
VISIBILITIES = frozenset({PRIVATE, PUBLIC})

LIST_SQL = """
SELECT id, name, visibility, updated_at
FROM strategies
WHERE user_id = %s
ORDER BY updated_at DESC, id DESC
"""

_FULL_SQL = """
SELECT id, user_id, name, visibility, document, ir, updated_at, created_at
FROM strategies
WHERE id = %s
"""


class _UnsetType:
    pass


UNSET = _UnsetType()


class StrategyNotFound(Exception):
    pass


class StrategyForbidden(Exception):
    pass


@dataclass(frozen=True)
class StrategyRow:
    id: int
    user_id: int
    name: str
    visibility: str
    document: Any
    ir: Any
    updated_at: datetime
    created_at: datetime


def normalize_visibility(visibility: object) -> str:
    if visibility not in VISIBILITIES:
        raise ValueError("visibility must be private or public")
    return str(visibility)


def can_view(owner_id: int, visibility: str, viewer_id: int) -> bool:
    return viewer_id == owner_id or visibility == PUBLIC


def can_edit(owner_id: int, viewer_id: int) -> bool:
    return viewer_id == owner_id


def clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise ValueError("Name is required")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Name is required")
    return cleaned


def _json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def new_strategy_values(user_id: int, name: object, document: object, ir: object) -> dict[str, Any]:
    """Fields for a strategy the caller owns. New strategies are private."""
    stored_ir = None if ir is None else _json_object(ir, "ir")
    return {
        "user_id": user_id,
        "name": clean_name(name),
        "visibility": PRIVATE,
        "document": _json_object(document, "document"),
        "ir": stored_ir,
    }


def copy_payload(viewer_id: int, name: str, document: Any, ir: Any) -> dict[str, Any]:
    """A new private strategy. Deep-copies document and ir so the source stays put."""
    return {
        "user_id": viewer_id,
        "name": name,
        "visibility": PRIVATE,
        "document": copy.deepcopy(document),
        "ir": copy.deepcopy(ir),
    }


def to_summary(strategy_id: int, name: str, visibility: str, updated_at: datetime) -> dict[str, Any]:
    return {
        "id": int(strategy_id),
        "name": name,
        "visibility": visibility,
        "updated_at": updated_at.isoformat(),
    }


def to_api(row: StrategyRow, viewer_id: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "visibility": row.visibility,
        "document": row.document,
        "ir": row.ir,
        "updated_at": row.updated_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "owned": can_edit(row.user_id, viewer_id),
    }


def create_strategy(user_id: int, name: str, document: Any, ir: Any = None) -> dict[str, Any]:
    values = new_strategy_values(user_id, name, document, ir)
    conn = _connect()
    try:
        with conn.transaction():
            record = conn.execute(
                """
                INSERT INTO strategies (user_id, name, visibility, document, ir)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_id, name, visibility, document, ir, updated_at, created_at
                """,
                _insert_params(values),
            ).fetchone()
        return to_api(_row_from_record(record), user_id)
    finally:
        conn.close()


def list_strategies(user_id: int) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        records = conn.execute(LIST_SQL, (user_id,)).fetchall()
    finally:
        conn.close()
    return [to_summary(record[0], record[1], record[2], record[3]) for record in records]


def get_strategy(viewer_id: int, strategy_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = _select_one(conn, strategy_id)
    finally:
        conn.close()
    if row is None or not can_view(row.user_id, row.visibility, viewer_id):
        raise StrategyNotFound()
    return to_api(row, viewer_id)


def update_strategy(
    user_id: int,
    strategy_id: int,
    *,
    name: Any = UNSET,
    document: Any = UNSET,
    ir: Any = UNSET,
    visibility: Any = UNSET,
) -> dict[str, Any]:
    conn = _connect()
    try:
        with conn.transaction():
            current = _select_one(conn, strategy_id)
            if current is None:
                raise StrategyNotFound()
            if not can_edit(current.user_id, user_id):
                raise StrategyForbidden()
            assignments, params = _assignments(
                name=name, document=document, ir=ir, visibility=visibility
            )
            if not assignments:
                raise ValueError("No fields to update")
            assignments.append("updated_at = now()")
            params.extend([strategy_id, user_id])
            record = conn.execute(
                f"""
                UPDATE strategies
                SET {", ".join(assignments)}
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, name, visibility, document, ir, updated_at, created_at
                """,
                params,
            ).fetchone()
        if record is None:
            raise StrategyNotFound()
        return to_api(_row_from_record(record), user_id)
    finally:
        conn.close()


def copy_strategy(viewer_id: int, strategy_id: int) -> int:
    conn = _connect()
    try:
        with conn.transaction():
            current = _select_one(conn, strategy_id)
            if current is None or not can_view(current.user_id, current.visibility, viewer_id):
                raise StrategyNotFound()
            payload = copy_payload(viewer_id, current.name, current.document, current.ir)
            record = conn.execute(
                """
                INSERT INTO strategies (user_id, name, visibility, document, ir)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                _insert_params(payload),
            ).fetchone()
        return int(record[0])
    finally:
        conn.close()


def _assignments(
    *,
    name: Any,
    document: Any,
    ir: Any,
    visibility: Any,
) -> tuple[list[str], list[Any]]:
    assignments: list[str] = []
    params: list[Any] = []
    if name is not UNSET:
        assignments.append("name = %s")
        params.append(clean_name(name))
    if document is not UNSET:
        assignments.append("document = %s")
        params.append(Jsonb(_json_object(document, "document")))
    if ir is not UNSET:
        stored_ir = None if ir is None else _json_object(ir, "ir")
        assignments.append("ir = %s")
        params.append(Jsonb(stored_ir) if stored_ir is not None else None)
    if visibility is not UNSET:
        assignments.append("visibility = %s")
        params.append(normalize_visibility(visibility))
    return assignments, params


def _insert_params(values: dict[str, Any]) -> tuple[Any, ...]:
    ir = values["ir"]
    return (
        values["user_id"],
        values["name"],
        values["visibility"],
        Jsonb(values["document"]),
        Jsonb(ir) if ir is not None else None,
    )


def _select_one(conn: psycopg.Connection, strategy_id: int) -> StrategyRow | None:
    record = conn.execute(_FULL_SQL, (strategy_id,)).fetchone()
    if record is None:
        return None
    return _row_from_record(record)


def _row_from_record(record: tuple) -> StrategyRow:
    return StrategyRow(
        id=int(record[0]),
        user_id=int(record[1]),
        name=str(record[2]),
        visibility=str(record[3]),
        document=_load_json(record[4]),
        ir=_load_json(record[5]),
        updated_at=record[6],
        created_at=record[7],
    )


def _load_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _connect() -> psycopg.Connection:
    return connect()
