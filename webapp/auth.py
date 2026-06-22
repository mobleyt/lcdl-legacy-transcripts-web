"""Shared-password gate.

A single password (``APP_PASSWORD``) protects the whole app. On success we set
a flag in the signed session cookie. ``require_login`` is a FastAPI dependency
that redirects unauthenticated browsers to the login page.
"""

from __future__ import annotations

import hmac

from fastapi import Request
from starlette.exceptions import HTTPException

from . import config


def check_password(candidate: str) -> bool:
    if config.ALLOW_NO_AUTH:
        return True
    if not config.APP_PASSWORD:
        return False
    return hmac.compare_digest(candidate, config.APP_PASSWORD)


def is_authenticated(request: Request) -> bool:
    if config.ALLOW_NO_AUTH:
        return True
    return bool(request.session.get("authed"))


async def require_login(request: Request) -> None:
    """Dependency for protected pages: redirect to /login if not signed in."""
    if not is_authenticated(request):
        # Raised as a redirect so the browser lands on the login form.
        raise HTTPException(
            status_code=307, headers={"Location": "/login"}, detail="login required"
        )
