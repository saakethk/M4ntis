"""Compile strategies with the TradeCPU compiler in ``dev/software/compiler``.

The compiler reads ``m4ntis.strategy/v1`` documents (the editor's saved format).
Macro blocks such as Z-Score are expanded first, and diagnostics that land on a
generated node are reported against the block the user placed.
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from src.backend.mantis.blocks.document import DOCUMENT_SCHEMA
from src.backend.mantis.blocks.macros import expand_document, source_node
from src.backend.mantis.config import COMPILER_ROOT
from src.backend.mantis.errors import InvalidInput
from src.backend.mantis.services import strategies

if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from tradecpu import CompileOptions, compile_to_json  # noqa: E402

IR_SCHEMA = "m4ntis.strategy-ir/v1"


class CompilationFailed(Exception):
    """The compiler rejected the document. ``diagnostics`` are ``{level, message, node?}``."""

    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(_describe(d) for d in diagnostics))


class InvalidCompileBody(Exception):
    """The request wrapper had unknown or mistyped fields. ``errors`` are pydantic errors."""

    def __init__(self, errors: list[Any]):
        self.errors = errors
        super().__init__("Invalid compile request")


class CompileBody(BaseModel):
    """``strategy_id`` and/or an inline ``document``.

    ``price_exponents`` maps a buffer (0-4) to how its prices are scaled into the
    16-bit tick field: 2 = cents (default), 1 = dimes, 0 = dollars. A stock above
    $327.67 cannot be sent in cents.
    """

    model_config = ConfigDict(extra="forbid")
    strategy_id: int | None = None
    document: dict[str, Any] | None = None
    price_exponents: dict[int, int] | None = None


def compile_document(document: dict[str, Any], price_exponents: dict[int, int] | None = None) -> dict[str, Any]:
    """Compile one document. Returns ``{ok, asm, hex, manifest, diagnostics}``.

    ``manifest["words"]`` is the program to upload to the board.
    """
    if not isinstance(document, dict):
        raise InvalidInput("document must be a JSON object")
    options = CompileOptions(price_exponents=dict(price_exponents or {}))
    try:
        result = compile_to_json(expand_document(document), options)
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        raise CompilationFailed([{"level": "error", "message": str(exc)}]) from exc
    result["diagnostics"] = [_to_source(d) for d in result["diagnostics"]]
    if not result["ok"]:
        raise CompilationFailed(result["diagnostics"])
    return result


def compile_request(user_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Compile a request body for a signed-in user.

    A body whose ``schema`` is the strategy document (or the IR, which the compiler
    rejects with its own message) is compiled as itself. Any other body is a
    :class:`CompileBody`. A strategy id is compiled only when the user can view
    it; when a document is also sent, the document is compiled after that check.
    """
    if body.get("schema") in (DOCUMENT_SCHEMA, IR_SCHEMA):
        if "strategy_id" in body:
            strategies.get_strategy(user_id, _strategy_id(body.get("strategy_id")))
        return compile_document(body)
    try:
        parsed = CompileBody.model_validate(body)
    except ValidationError as exc:
        raise InvalidCompileBody(exc.errors()) from exc
    document = parsed.document
    if parsed.strategy_id is not None:
        stored = strategies.get_strategy(user_id, parsed.strategy_id)
        document = document if document is not None else stored["document"]
    if not isinstance(document, dict):
        raise InvalidInput("A strategy document or strategy id is required")
    return compile_document(document, parsed.price_exponents)


def check_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Diagnostics only (errors included). Used by the assistant to test its drafts."""
    try:
        return compile_document(document)["diagnostics"]
    except CompilationFailed as exc:
        return exc.diagnostics


def _strategy_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidCompileBody([{"loc": ["strategy_id"], "msg": "strategy_id must be an integer", "type": "int_type"}])
    return value


def _to_source(diagnostic: dict[str, Any]) -> dict[str, Any]:
    node = source_node(diagnostic.get("node"))
    return {**diagnostic, "node": node} if node else diagnostic


def _describe(diagnostic: dict[str, Any]) -> str:
    text = f"{diagnostic.get('level', 'error')}: {diagnostic.get('message', '')}"
    return text + (f" [{diagnostic['node']}]" if diagnostic.get("node") else "")
