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


def new_strategy_values(
    user_id: int,
    name: object,
    document: object,
    ir: object,
    visibility: object = PRIVATE,
) -> dict[str, Any]:
    """Fields for a strategy the caller owns. Visibility defaults to private."""
    stored_ir = None if ir is None else _json_object(ir, "ir")
    return {
        "user_id": user_id,
        "name": clean_name(name),
        "visibility": normalize_visibility(visibility),
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


def create_strategy(
    user_id: int,
    name: str,
    document: Any,
    ir: Any = None,
    visibility: object = PRIVATE,
) -> dict[str, Any]:
    values = new_strategy_values(user_id, name, document, ir, visibility)
    conn = _connect()
    try:
        # connect() already ran SET TIME ZONE, which opens a transaction.
        # transaction() would only be a savepoint, and close() would roll the
        # insert back. The API would return an id that never shows up later.
        conn.commit()
        with conn.transaction():
            record = conn.execute(
                """
                INSERT INTO strategies (user_id, name, visibility, document, ir)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_id, name, visibility, document, ir, updated_at, created_at
                """,
                _insert_params(values),
            ).fetchone()
            row = _row_from_record(record)
            _insert_version(conn, row.id, row.document, row.ir)
        return to_summary(row.id, row.name, row.visibility, row.updated_at)
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
        conn.commit()
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
            row = _row_from_record(record)
            if document is not UNSET or ir is not UNSET:
                _insert_version(conn, row.id, row.document, row.ir)
        return to_summary(row.id, row.name, row.visibility, row.updated_at)
    finally:
        conn.close()


def copy_strategy(viewer_id: int, strategy_id: int) -> int:
    conn = _connect()
    try:
        conn.commit()
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
            new_id = int(record[0])
            _insert_version(conn, new_id, payload["document"], payload["ir"])
        return new_id
    finally:
        conn.close()


def list_versions(user_id: int, strategy_id: int) -> list[dict[str, Any]]:
    """Saved versions for the owner, newest first. Backtest snapshots are omitted."""
    conn = _connect()
    try:
        current = _owned(conn, user_id, strategy_id)
        records = conn.execute(
            """
            SELECT id, document, created_at
            FROM strategy_versions
            WHERE strategy_id = %s AND kind = 'save'
            ORDER BY created_at DESC, id DESC
            """,
            (strategy_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(record[0]),
            "name": _version_name(_load_json(record[1]), current.name),
            "created_at": record[2].isoformat(),
        }
        for record in records
    ]


def revert_version(user_id: int, strategy_id: int, version_id: int) -> dict[str, Any]:
    """Copy a saved version onto the strategy and keep that restore in the history."""
    conn = _connect()
    try:
        conn.commit()
        with conn.transaction():
            current = _owned(conn, user_id, strategy_id)
            version = conn.execute(
                """
                SELECT document, ir
                FROM strategy_versions
                WHERE id = %s AND strategy_id = %s AND kind = 'save'
                """,
                (version_id, strategy_id),
            ).fetchone()
            if version is None:
                raise StrategyNotFound()
            document = _load_json(version[0])
            ir = _load_json(version[1])
            name = _version_name(document, current.name)
            record = conn.execute(
                """
                UPDATE strategies
                SET name = %s, document = %s, ir = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, name, visibility, document, ir, updated_at, created_at
                """,
                (
                    name,
                    Jsonb(document),
                    Jsonb(ir) if ir is not None else None,
                    strategy_id,
                    user_id,
                ),
            ).fetchone()
            if record is None:
                raise StrategyNotFound()
            row = _row_from_record(record)
            _insert_version(conn, row.id, row.document, row.ir)
        return to_api(row, user_id)
    finally:
        conn.close()


def _owned(conn: psycopg.Connection, user_id: int, strategy_id: int) -> StrategyRow:
    current = _select_one(conn, strategy_id)
    if current is None or not can_view(current.user_id, current.visibility, user_id):
        raise StrategyNotFound()
    if not can_edit(current.user_id, user_id):
        raise StrategyForbidden()
    return current


def _version_name(document: Any, fallback: str) -> str:
    if isinstance(document, dict) and isinstance(document.get("name"), str):
        cleaned = document["name"].strip()
        if cleaned:
            return cleaned
    return fallback


def _insert_version(conn: psycopg.Connection, strategy_id: int, document: Any, ir: Any) -> None:
    conn.execute(
        """
        INSERT INTO strategy_versions (strategy_id, document, ir, kind)
        VALUES (%s, %s, %s, 'save')
        """,
        (
            strategy_id,
            Jsonb(document),
            Jsonb(ir) if ir is not None else None,
        ),
    )


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
