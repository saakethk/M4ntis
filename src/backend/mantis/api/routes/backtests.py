"""Backtest runs under ``/backtests``. Runs execute on the TradeCPU FPGA only; without a board they fail with 503."""

from __future__ import annotations

from fastapi import APIRouter

from src.backend.mantis.api.deps import CurrentUser
from src.backend.mantis.api.schemas import BacktestCreate
from src.backend.mantis.services import backtests

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("/fpga")
def fpga(_: CurrentUser) -> dict:
    return backtests.fpga_status()


@router.get("/range")
def range(strategy_id: int, user: CurrentUser) -> dict:
    return backtests.backtest_available_range(user.id, strategy_id)


@router.post("", status_code=201)
def run(body: BacktestCreate, user: CurrentUser) -> dict:
    return backtests.run_backtest(user.id, body.user_id, body.strategy_id, body.start, body.end)


@router.get("/{backtest_id:int}")
def get(backtest_id: int, user: CurrentUser) -> dict:
    return backtests.get_backtest(user.id, backtest_id)
