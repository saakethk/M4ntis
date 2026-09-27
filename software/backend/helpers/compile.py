"""Compile a strategy with the TradeCPU compiler in software/compiler.

The compiler reads an ``m4ntis.strategy/v1`` document (the editor's
``toDocument()`` file). It does not read ``m4ntis.strategy-ir/v1``. An IR body
is still accepted and fails with the compiler's own message.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

import helpers.strategies as strategies

_COMPILER_ROOT = Path(__file__).resolve().parents[2] / "compiler"
if str(_COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPILER_ROOT))

from tradecpu.asm import format_asm  # noqa: E402
from tradecpu.compiler import CompileError, compile_strategy  # noqa: E402

DOCUMENT_SCHEMA = "m4ntis.strategy/v1"
IR_SCHEMA = "m4ntis.strategy-ir/v1"
_COMPILER_SCHEMAS = frozenset({DOCUMENT_SCHEMA, IR_SCHEMA})


class CompileBody(BaseModel):
    """Saved strategy id and/or an inline document. The document stays free-form."""

    model_config = ConfigDict(extra="forbid")
    strategy_id: int | None = None
    document: dict[str, Any] | None = None


class _StrategyId(BaseModel):
    """Read strategy_id off a free-form compiler payload without rejecting its fields."""

    model_config = ConfigDict(extra="ignore")
    strategy_id: int


class CompilationFailed(Exception):
    """The compiler rejected the document. ``str(exc)`` is the compiler message."""


class InvalidCompileBody(Exception):
    def __init__(self, errors: list[Any]):
        self.errors = errors
        super().__init__("Invalid compile request")


def compile_document(document: dict[str, Any]) -> dict[str, Any]:
    """Compile one strategy document. Returns the compiler's JSON object.

    Same fields as ``python -m tradecpu compile - --json``: ``ok``, ``asm``,
    ``hex``, ``manifest``, and ``diagnostics``.
    """
    if not isinstance(document, dict):
        raise ValueError("document must be a JSON object")
    try:
        result = compile_strategy(document)
    except CompileError as exc:
        raise CompilationFailed(str(exc)) from exc
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        raise CompilationFailed(f"error: {exc}") from exc
    return {
        "ok": True,
        "asm": format_asm(result.items, addresses=True),
        "hex": result.assembled.hex_lines(),
        "manifest": result.manifest,
        "diagnostics": [warning.to_json() for warning in result.warnings],
    }


def compile_request(user_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Compile a request body for a signed-in user.

    A body whose ``schema`` is the strategy document or the IR is compiled as
    itself. Any other object is ``{strategy_id?, document?}`` and rejects
    unknown fields. A strategy id is compiled only when ``user_id`` can view
    that strategy. When both an id and a document are present, the document is
    what gets compiled, after the view check.
    """
    if body.get("schema") in _COMPILER_SCHEMAS:
        if "strategy_id" in body:
            _require_visible(user_id, _read_strategy_id(body))
        return compile_document(body)

    parsed = _parse_wrapper(body)
    document = parsed.document
    if parsed.strategy_id is not None:
        stored = _require_visible(user_id, parsed.strategy_id)
        if document is None:
            document = stored["document"]
    if not isinstance(document, dict):
        raise ValueError("A strategy document or strategy id is required")
    return compile_document(document)


def _require_visible(user_id: int, strategy_id: int) -> dict[str, Any]:
    return strategies.get_strategy(user_id, strategy_id)


def _parse_wrapper(body: dict[str, Any]) -> CompileBody:
    try:
        return CompileBody.model_validate(body)
    except ValidationError as exc:
        raise InvalidCompileBody(exc.errors()) from exc


def _read_strategy_id(body: dict[str, Any]) -> int:
    try:
        return _StrategyId.model_validate(body).strategy_id
    except ValidationError as exc:
        raise InvalidCompileBody(exc.errors()) from exc
