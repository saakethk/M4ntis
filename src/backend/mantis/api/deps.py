"""Request dependencies shared by the routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Response

from src.backend.mantis.errors import NotSignedIn
from src.backend.mantis.services import auth


def current_user(request: Request) -> auth.User:
    """The signed-in user from the session cookie, or 401."""
    user = auth.user_from_token(request.cookies.get(auth.SESSION_COOKIE, ""))
    if user is None:
        raise NotSignedIn()
    return user


CurrentUser = Annotated[auth.User, Depends(current_user)]


def set_session_cookie(response: Response, token: str) -> None:
    # Host-only (no Domain) and SameSite=Lax: the Vite dev proxy keeps the page and
    # API on one site, so the cookie is first-party. Secure stays off so plain-HTTP
    # local development can store it; SameSite=None would require Secure.
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=auth.SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )
