"""CSRF protection for SPECTRE.

Token = itsdangerous HMAC of a fixed payload keyed on (SECRET_KEY, session_cookie).
Same session → same token. Automatically invalidated on login/logout because the
session cookie changes.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, Signer

from spectre.config.settings import get_settings

logger = logging.getLogger(__name__)

_CSRF_HEADER = "X-CSRF-Token"
_CSRF_FIELD = "csrf_token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_EXEMPT_PATHS = frozenset({"/login"})
_FORM_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
})


def _signer(session_cookie: str) -> Signer:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    # Incorporate first 32 chars of the session cookie into the salt so the
    # token is unique per session without requiring a DB lookup.
    return Signer(settings.secret_key, salt=f"spectre-csrf:{session_cookie[:32]}")


def make_csrf_token(session_cookie: str) -> str:
    """Return a CSRF token bound to *session_cookie*."""
    return _signer(session_cookie).sign(b"csrf").decode()


def verify_csrf_token(session_cookie: str, submitted: str) -> bool:
    """Return True iff *submitted* is the valid CSRF token for *session_cookie*."""
    if not submitted or not session_cookie:
        return False
    try:
        _signer(session_cookie).unsign(submitted.encode())
        return True
    except BadSignature:
        return False


async def require_csrf(request: Request) -> None:
    """Global FastAPI dependency: reject non-safe requests without a valid CSRF token.

    HTMX requests carry the token in X-CSRF-Token (configured via hx-headers on
    <body>). Plain HTML form submissions carry it in a hidden csrf_token field.
    GET/HEAD/OPTIONS/TRACE and the public /login POST are exempted.
    """
    if request.method in _SAFE_METHODS:
        return
    if request.url.path in _EXEMPT_PATHS:
        return

    session_cookie = request.cookies.get("spectre_session", "")

    # 1. Header — HTMX sends this on every request when hx-headers is set on <body>.
    token = request.headers.get(_CSRF_HEADER, "")

    # 2. Form field fallback — plain HTML <form method="post"> submissions.
    if not token:
        content_type = request.headers.get("content-type", "").split(";")[0].strip()
        if content_type in _FORM_CONTENT_TYPES:
            try:
                form = await request.form()
                token = str(form.get(_CSRF_FIELD, "") or "")
            except Exception:
                token = ""

    if not verify_csrf_token(session_cookie, token):
        logger.warning("CSRF check failed — method=%s path=%s", request.method, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
