"""Saved strategies, copies, and version history under ``/strategies``."""

from __future__ import annotations

from fastapi import APIRouter

from mantis.api.deps import CurrentUser
from mantis.api.schemas import StrategyCreate, StrategyUpdate
from mantis.services import backtest_summaries, strategies

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.post("", status_code=201)
def create(body: StrategyCreate, user: CurrentUser) -> dict:
    return strategies.create_strategy(user.id, body.name, body.document, body.ir, body.visibility)


@router.get("")
def list_owned(user: CurrentUser) -> list:
    return backtest_summaries.list_strategies_with_latest(user.id)


@router.get("/{strategy_id}")
def get(strategy_id: int, user: CurrentUser) -> dict:
    return strategies.get_strategy(user.id, strategy_id)


@router.put("/{strategy_id}")
def update(strategy_id: int, body: StrategyUpdate, user: CurrentUser) -> dict:
    sent = {name: getattr(body, name) for name in body.model_fields_set}
    return strategies.update_strategy(user.id, strategy_id, **sent)


@router.post("/{strategy_id}/copy", status_code=201)
def copy(strategy_id: int, user: CurrentUser) -> dict:
    return {"id": strategies.copy_strategy(user.id, strategy_id)}


@router.get("/{strategy_id}/versions")
def versions(strategy_id: int, user: CurrentUser) -> list:
    return strategies.list_versions(user.id, strategy_id)


@router.post("/{strategy_id}/versions/{version_id}/revert")
def revert(strategy_id: int, version_id: int, user: CurrentUser) -> dict:
    return strategies.revert_version(user.id, strategy_id, version_id)
