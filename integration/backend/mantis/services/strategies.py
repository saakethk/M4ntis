"""Saved strategies, their version history, and who may see or change them.

A strategy is ``private`` (owner only) or ``public`` (any signed-in user may view
it). Only the owner can edit. Another user who wants to change a public strategy
copies it into a new private strategy they own; the original is untouched.

Every save of the document or IR also records a ``strategy_versions`` row of kind
``save`` so the owner can revert. Backtests record their own snapshot of kind
``backtest``; those are not listed as saved versions.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from mantis import db
from mantis.errors import Forbidden, InvalidInput, NotFound

PRIVATE = "private"
PUBLIC = "public"
VISIBILITIES = (PRIVATE, PUBLIC)

_COLUMNS = "id, user_id, name, visibility, document, ir, updated_at, created_at"


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()
"""Marks an update field the caller did not send, as opposed to one sent as null."""


class StrategyNotFound(NotFound):
    def __init__(self, detail: str = "Strategy not found"):
        super().__init__(detail)


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

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "visibility": self.visibility,
            "updated_at": self.updated_at.isoformat(),
        }

    def to_api(self, viewer_id: int) -> dict[str, Any]:
        return {
            **self.summary(),
            "user_id": self.user_id,
            "document": self.document,
            "ir": self.ir,
            "created_at": self.created_at.isoformat(),
            "owned": can_edit(self.user_id, viewer_id),
        }


def can_view(owner_id: int, visibility: str, viewer_id: int) -> bool:
    return viewer_id == owner_id or visibility == PUBLIC


def can_edit(owner_id: int, viewer_id: int) -> bool:
    return viewer_id == owner_id


def normalize_visibility(visibility: object) -> str:
    if visibility not in VISIBILITIES:
        raise InvalidInput("visibility must be private or public")
    return str(visibility)


def clean_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise InvalidInput("Name is required")
    return name.strip()


def create_strategy(
    user_id: int,
    name: object,
    document: object,
    ir: object = None,
    visibility: object = PRIVATE,
) -> dict[str, Any]:
    values = (
        user_id,
        clean_name(name),
        normalize_visibility(visibility),
        Jsonb(_json_object(document, "document")),
        _optional_json(ir),
    )
    with db.session() as conn, conn.transaction():
        row = _row(
            conn.execute(
                f"""
                INSERT INTO strategies (user_id, name, visibility, document, ir)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_COLUMNS}
                """,
                values,
            ).fetchone()
        )
        _record_version(conn, row)
    return row.summary()


def list_strategies(user_id: int) -> list[dict[str, Any]]:
    """Strategies the user owns, most recently updated first."""
    with db.session() as conn:
        records = conn.execute(
            f"SELECT {_COLUMNS} FROM strategies WHERE user_id = %s ORDER BY updated_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [_row(record).summary() for record in records]


def get_strategy(viewer_id: int, strategy_id: int) -> dict[str, Any]:
    with db.session() as conn:
        return _viewable(conn, viewer_id, strategy_id).to_api(viewer_id)


def update_strategy(
    user_id: int,
    strategy_id: int,
    *,
    name: Any = UNSET,
    document: Any = UNSET,
    ir: Any = UNSET,
    visibility: Any = UNSET,
) -> dict[str, Any]:
    """Change the fields the caller sent. Only the owner may update."""
    assignments: list[str] = []
    params: list[Any] = []
    if name is not UNSET:
        assignments.append("name = %s")
        params.append(clean_name(name))
    if document is not UNSET:
        assignments.append("document = %s")
        params.append(Jsonb(_json_object(document, "document")))
    if ir is not UNSET:
        assignments.append("ir = %s")
        params.append(_optional_json(ir))
    if visibility is not UNSET:
        assignments.append("visibility = %s")
        params.append(normalize_visibility(visibility))
    if not assignments:
        raise InvalidInput("No fields to update")

    with db.session() as conn, conn.transaction():
        _owned(conn, user_id, strategy_id, "Only the owner can change this strategy")
        row = _row(
            conn.execute(
                f"""
                UPDATE strategies SET {", ".join(assignments)}, updated_at = now()
                WHERE id = %s AND user_id = %s
                RETURNING {_COLUMNS}
                """,
                [*params, strategy_id, user_id],
            ).fetchone()
        )
        if document is not UNSET or ir is not UNSET:
            _record_version(conn, row)
    return row.summary()


def copy_strategy(viewer_id: int, strategy_id: int) -> int:
    """Copy a strategy the viewer can see into a new private strategy they own."""
    with db.session() as conn, conn.transaction():
        source = _viewable(conn, viewer_id, strategy_id)
        row = _row(
            conn.execute(
                f"""
                INSERT INTO strategies (user_id, name, visibility, document, ir)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_COLUMNS}
                """,
                (
                    viewer_id,
                    source.name,
                    PRIVATE,
                    Jsonb(copy.deepcopy(source.document)),
                    _optional_json(copy.deepcopy(source.ir)),
                ),
            ).fetchone()
        )
        _record_version(conn, row)
    return row.id


def list_versions(user_id: int, strategy_id: int) -> list[dict[str, Any]]:
    """Saved versions for the owner, newest first."""
    with db.session() as conn:
        current = _owned(conn, user_id, strategy_id, "Only the owner can view saved versions")
        records = conn.execute(
            """
            SELECT id, document, created_at FROM strategy_versions
            WHERE strategy_id = %s AND kind = 'save'
            ORDER BY created_at DESC, id DESC
            """,
            (strategy_id,),
        ).fetchall()
    return [
        {
            "id": int(record[0]),
            "name": _version_name(record[1], current.name),
            "created_at": record[2].isoformat(),
        }
        for record in records
    ]


def revert_version(user_id: int, strategy_id: int, version_id: int) -> dict[str, Any]:
    """Copy a saved version onto the strategy and record the restore as a new version."""
    with db.session() as conn, conn.transaction():
        current = _owned(conn, user_id, strategy_id, "Only the owner can revert this strategy")
        version = conn.execute(
            """
            SELECT document, ir FROM strategy_versions
            WHERE id = %s AND strategy_id = %s AND kind = 'save'
            """,
            (version_id, strategy_id),
        ).fetchone()
        if version is None:
            raise NotFound("Saved version not found")
        document, ir = version
        row = _row(
            conn.execute(
                f"""
                UPDATE strategies SET name = %s, document = %s, ir = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                RETURNING {_COLUMNS}
                """,
                (
                    _version_name(document, current.name),
                    Jsonb(document),
                    _optional_json(ir),
                    strategy_id,
                    user_id,
                ),
            ).fetchone()
        )
        _record_version(conn, row)
    return row.to_api(user_id)


def load_viewable(conn: psycopg.Connection, viewer_id: int, strategy_id: int) -> StrategyRow:
    """The strategy row when the viewer may see it. Shared with backtests and discussions."""
    return _viewable(conn, viewer_id, strategy_id)


def _select(conn: psycopg.Connection, strategy_id: int) -> StrategyRow | None:
    record = conn.execute(f"SELECT {_COLUMNS} FROM strategies WHERE id = %s", (strategy_id,)).fetchone()
    return None if record is None else _row(record)


def _viewable(conn: psycopg.Connection, viewer_id: int, strategy_id: int) -> StrategyRow:
    # A private strategy someone else owns is reported as missing, not forbidden,
    # so ids of other users' private work are not revealed.
    row = _select(conn, strategy_id)
    if row is None or not can_view(row.user_id, row.visibility, viewer_id):
        raise StrategyNotFound()
    return row


def _owned(conn: psycopg.Connection, user_id: int, strategy_id: int, forbidden: str) -> StrategyRow:
    row = _viewable(conn, user_id, strategy_id)
    if not can_edit(row.user_id, user_id):
        raise Forbidden(forbidden)
    return row


def _record_version(conn: psycopg.Connection, row: StrategyRow) -> None:
    conn.execute(
        "INSERT INTO strategy_versions (strategy_id, document, ir, kind) VALUES (%s, %s, %s, 'save')",
        (row.id, Jsonb(row.document), _optional_json(row.ir)),
    )


def _version_name(document: Any, fallback: str) -> str:
    if isinstance(document, dict) and isinstance(document.get("name"), str) and document["name"].strip():
        return document["name"].strip()
    return fallback


def _json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInput(f"{label} must be a JSON object")
    return value


def _optional_json(value: object) -> Jsonb | None:
    return None if value is None else Jsonb(_json_object(value, "ir"))


def _row(record: tuple) -> StrategyRow:
    return StrategyRow(
        id=int(record[0]),
        user_id=int(record[1]),
        name=str(record[2]),
        visibility=str(record[3]),
        document=record[4],
        ir=record[5],
        updated_at=record[6],
        created_at=record[7],
    )
