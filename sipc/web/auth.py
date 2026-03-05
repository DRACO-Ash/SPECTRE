"""Session cookie auth helpers and FastAPI dependency for SIPC."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sipc.config.settings import get_settings
from sipc.web.database import get_db
from sipc.web.models import User

logger = logging.getLogger(__name__)

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Session cookie expires after 8 hours (28 800 seconds).
_SESSION_MAX_AGE = 28_800
_COOKIE_NAME = "sipc_session"


def _serializer() -> URLSafeTimedSerializer:
    """Return a signer seeded from the current SECRET_KEY setting."""
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return URLSafeTimedSerializer(settings.secret_key, salt="sipc-session")


# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(plaintext: str) -> str:
    """Return the bcrypt hash of *plaintext*."""
    return _pwd_ctx.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return ``True`` if *plaintext* matches *hashed*."""
    return bool(_pwd_ctx.verify(plaintext, hashed))


# ── Cookie helpers ────────────────────────────────────────────────────────────


def make_session_cookie(username: str) -> str:
    """Create a signed, time-limited session token for *username*."""
    return str(_serializer().dumps({"sub": username}))


def decode_session_cookie(token: str) -> str | None:
    """Decode and validate *token*.

    Returns the username on success, or ``None`` if the token is expired/invalid.
    """
    try:
        data = _serializer().loads(token, max_age=_SESSION_MAX_AGE)
        return str(data["sub"])
    except (SignatureExpired, BadSignature, KeyError):
        return None


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def require_login(
    sipc_session: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that validates the session cookie.

    Returns the authenticated :class:`~sipc.web.models.User` on success.
    Raises HTTP 302 (redirect to /login) if the session is missing or invalid.
    """
    from fastapi.responses import RedirectResponse  # noqa: PLC0415

    if not sipc_session:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    username = decode_session_cookie(sipc_session)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("Session for unknown user: %s", username)
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    return user
