"""Accounts and sessions: ``/auth/register``, ``/auth/login``, ``/auth/logout``, ``/auth/me``."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from mantis.api.deps import CurrentUser, set_session_cookie
from mantis.api.schemas import Credentials
from mantis.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(body: Credentials, response: Response) -> dict:
    user, token = auth.register(body.email, body.password)
    set_session_cookie(response, token)
    return user.to_api()


@router.post("/login")
def login(body: Credentials, response: Response) -> dict:
    user, token = auth.login(body.email, body.password)
    set_session_cookie(response, token)
    return user.to_api()


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    auth.logout(request.cookies.get(auth.SESSION_COOKIE, ""))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return user.to_api()
