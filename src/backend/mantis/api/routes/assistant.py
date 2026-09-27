"""The strategy assistant: ``POST /llm`` and the model list at ``GET /llm/models``."""

from __future__ import annotations

from fastapi import APIRouter

from src.backend.mantis.ai import assistant
from src.backend.mantis.ai import models
from src.backend.mantis.api.deps import CurrentUser
from src.backend.mantis.api.schemas import AssistantAsk

router = APIRouter(prefix="/llm", tags=["assistant"])


@router.get("/models")
def list_models(_: CurrentUser) -> dict:
    return models.models_for_api()


@router.post("")
def ask(body: AssistantAsk, _: CurrentUser) -> dict:
    return assistant.ask(
        body.prompt,
        body.graph.model_dump() if body.graph is not None else None,
        provider=body.provider,
        model=body.model,
        history=[turn.model_dump() for turn in body.history],
    )
