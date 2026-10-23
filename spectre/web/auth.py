"""Session cookie auth helpers and FastAPI dependency for SPECTRE."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

import bcrypt
from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.config.settings import get_settings
from spectre.web.database import get_db
from spectre.web.log_safety import log_safe
from spectre.web.models import User

logger = logging.getLogger(__name__)

# Session cookie expires after 8 hours (28 800 seconds).
_SESSION_MAX_AGE = 28_800
_COOKIE_NAME = "spectre_session"


def _serializer() -> URLSafeTimedSerializer:
    """Return a signer seeded from the current SECRET_KEY setting."""
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return URLSafeTimedSerializer(settings.secret_key, salt="spectre-session")


# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(plaintext: str) -> str:
    """Return the bcrypt hash of *plaintext*."""
    hashed: bytes = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt())
    return hashed.decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return ``True`` if *plaintext* matches *hashed*."""
    return bool(bcrypt.checkpw(plaintext.encode(), hashed.encode()))


# ── Cookie helpers ────────────────────────────────────────────────────────────


def make_session_cookie(username: str) -> str:
    """Create a signed, time-limited session token for *username*."""
    return str(_serializer().dumps({"sub": username}))


def _decode_session(token: str) -> tuple[str, datetime] | None:
    """Return the username and the issue time carried by *token*, or ``None``.

    The issue time is what makes a session revocable. itsdangerous signs it
    into the token itself, so a cookie copied off a shared terminal still says
    exactly when it was minted and can be weighed against the account's
    session epoch. ``None`` means expired, tampered with, or not one of ours.
    """
    try:
        data, issued_at = _serializer().loads(
            token, max_age=_SESSION_MAX_AGE, return_timestamp=True
        )
        return str(data["sub"]), issued_at
    except (SignatureExpired, BadSignature, KeyError):
        return None


def decode_session_cookie(token: str) -> str | None:
    """Decode and validate *token*.

    Returns the username on success, or ``None`` if the token is expired/invalid.
    """
    claims = _decode_session(token)
    return None if claims is None else claims[0]


def _session_revoked(user: User, issued_at: datetime) -> bool:
    """Return ``True`` when a token minted at *issued_at* has been revoked.

    Deleting the cookie at logout only asks the browser to forget it. The
    signed token stays good for its full 8 hours, so a copy taken from a
    shared operations-room terminal outlived the operator who logged out, and
    a password change left the sessions it was meant to answer untouched.
    Logout and password change move the epoch forward; this is where that
    movement is enforced.

    itsdangerous stamps whole seconds, so a token minted in the same second as
    the revocation is refused along with the ones that came before it. That is
    the safe way to lose the comparison: the operator signs in again a moment
    later, whereas the other way round leaves a live token behind a logout.

    SQLite hands back a naive datetime for a column declared with a time zone,
    so a stored epoch without one is read as the UTC it was written as rather
    than compared against an aware value, which would raise TypeError.
    """
    epoch = user.session_epoch
    if epoch is None:
        return False  # row predates the column, so nothing has been revoked
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=UTC)
    return issued_at < epoch


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def require_login(
    spectre_session: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that validates the session cookie.

    Returns the authenticated :class:`~spectre.web.models.User` on success.
    Raises HTTP 302 (redirect to /login) if the session is missing or invalid.
    """

    if not spectre_session:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    claims = _decode_session(spectre_session)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    username, issued_at = claims

    result = await db.execute(select(User).where(User.username == username))
    user: User | None = result.scalar_one_or_none()
    if user is None:
        logger.warning("Session for unknown user: %s", username)
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    if _session_revoked(user, issued_at):
        logger.info("Refused a session ended by logout or password change: %s", log_safe(username))
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    return user


async def require_admin(
    current_user: User = Depends(require_login),
) -> User:
    """FastAPI dependency that requires admin role.

    Wraps :func:`require_login`; raises HTTP 403 if the authenticated user is
    not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


async def optional_login(
    # Annotated rather than a Depends default (python:S8410). Annotated carries
    # no default, so this parameter has to precede the cookie, which does have
    # one. FastAPI resolves dependencies by name and the only call site is
    # Depends(optional_login), so no caller passes these positionally.
    db: Annotated[AsyncSession, Depends(get_db)],
    spectre_session: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
) -> User | None:
    """Return the authenticated user, or ``None`` when there is no valid session.

    Unlike :func:`require_login` this never raises, so a route can serve a
    public response to an anonymous caller. It exists for ``GET /``: the App
    Store router probes the root and requires 200, not the 302 that
    :func:`require_login` produces, while the console itself stays private.
    """
    if not spectre_session:
        return None

    claims = _decode_session(spectre_session)
    if claims is None:
        return None
    username, issued_at = claims

    result = await db.execute(select(User).where(User.username == username))
    user: User | None = result.scalar_one_or_none()
    # A session ended by logout or a password change must read as anonymous
    # here too, or the console greets the operator by name on the public page
    # after they have signed out of it.
    if user is None or _session_revoked(user, issued_at):
        return None
    return user
