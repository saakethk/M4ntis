"""``POST /compile``: compile a strategy document or a saved strategy for TradeCPU."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mantis.api.deps import CurrentUser
from mantis.services import compiler

router = APIRouter(tags=["compile"])


@router.post("/compile")
def compile_strategy(body: dict[str, Any], user: CurrentUser) -> dict:
    return compiler.compile_request(user.id, body)
