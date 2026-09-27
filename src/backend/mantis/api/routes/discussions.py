"""Discussion posts, likes, and AI thread summaries under ``/discussions``."""

from __future__ import annotations

from fastapi import APIRouter

from src.backend.mantis.ai.summaries import summarize_thread
from src.backend.mantis.api.deps import CurrentUser
from src.backend.mantis.api.schemas import DiscussionCreate, SummaryRequest
from src.backend.mantis.services import discussions

router = APIRouter(prefix="/discussions", tags=["discussions"])


@router.get("")
def list_posts(user: CurrentUser) -> list[dict]:
    return discussions.list_posts(user.id)


@router.post("", status_code=201)
def create(body: DiscussionCreate, user: CurrentUser) -> dict:
    return discussions.create_post(user.id, body.body, strategy_id=body.strategy_id, parent_id=body.parent_id)


@router.post("/{post_id}/like")
def like(post_id: int, user: CurrentUser) -> dict:
    return discussions.toggle_like(user.id, post_id)


@router.post("/{post_id}/summary")
def summarize(post_id: int, _: CurrentUser, body: SummaryRequest | None = None) -> dict:
    return discussions.summarize_post(post_id, summarize_thread, refresh=bool(body and body.refresh))
