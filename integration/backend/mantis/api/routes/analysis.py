"""``POST /backtests/{id}/analysis``: an AI explanation of a finished backtest."""

from __future__ import annotations

from fastapi import APIRouter

from mantis.ai import backtest_analysis
from mantis.api.deps import CurrentUser
from mantis.api.schemas import AnalysisRequest

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/{backtest_id}/analysis")
def analyze(backtest_id: int, user: CurrentUser, body: AnalysisRequest | None = None) -> dict:
    request = body or AnalysisRequest()
    return backtest_analysis.analyze(
        user.id, backtest_id, provider=request.provider, model=request.model, question=request.question
    )
