"""Session cookie auth helpers and FastAPI dependency for SPECTRE."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.config.settings import get_settings
from spectre.web.database import get_db
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey, User

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


@dataclass(frozen=True)
class SessionClaims:
    """What a session token says about whose session it is."""

    username: str
    user_id: int | None
    generation: int
    nonce: str = ""
    session_id: str = ""

    @property
    def key(self) -> SessionKey | None:
        """The sign-in this token belongs to, or ``None`` for a token naming no account."""
        return None if self.user_id is None else SessionKey(self.user_id, self.session_id)


def make_session_cookie(
    username: str, generation: int = 0, user_id: int | None = None, nonce: str = "", session_id: str = "",
) -> str:
    """Create a signed, time-limited session token for *username*.

    *generation* is the account's session generation at the moment of signing
    in. It travels in the payload so that a later logout or password change,
    which increments the stored counter, refuses this token by value rather
    than by clock.

    *user_id* binds the token to the account rather than the name. Without it
    a token outlived the account it was issued to: delete "alice", create a
    new "alice", and every unexpired token of the old one opened the new one,
    with the new one's role (audit F-048). A token with no id is refused by
    :func:`require_login`. *nonce* is the account's random ``session_nonce``,
    which a recreated namesake does not share even when SQLite reuses the id.
    *session_id* is random per sign-in and files the planning state.
    """
    payload: dict[str, object] = {"sub": username, "gen": int(generation), "non": nonce, "sid": session_id}
    if user_id is not None:
        payload["uid"] = int(user_id)
    return str(_serializer().dumps(payload))


def _decode_session(token: str) -> SessionClaims | None:
    """Return the claims carried by *token*.

    ``None`` means expired, tampered with, or not one of ours.
    """
    try:
        data = _serializer().loads(token, max_age=_SESSION_MAX_AGE)
        uid = data.get("uid")
        return SessionClaims(
            username=str(data["sub"]),
            user_id=None if uid is None else int(uid),
            generation=int(data.get("gen", 0)),
            nonce=str(data.get("non", "")),
            session_id=str(data.get("sid", "")),
        )
    except (SignatureExpired, BadSignature, KeyError, TypeError, ValueError, AttributeError):
        return None


def session_key_for(token: str) -> SessionKey | None:
    """The sign-in *token* belongs to, without checking it is still current."""
    claims = _decode_session(token)
    return None if claims is None else claims.key


async def current_user_for(token: str, db: AsyncSession) -> User | None:
    """The account *token* is a live session of, or ``None``.

    For the routes that read the cookie themselves rather than through
    :func:`require_login`, so they apply the same binding and revocation.
    """
    claims = _decode_session(token)
    if claims is None:
        return None
    result = await db.execute(select(User).where(User.username == claims.username))
    user: User | None = result.scalar_one_or_none()
    if user is None or not _bound_to(user, claims):
        return None
    user.session_key = claims.key
    return user


def decode_session_cookie(token: str) -> str | None:
    """Decode and validate *token*.

    Returns the username on success, or ``None`` if the token is expired/invalid.
    """
    claims = _decode_session(token)
    return None if claims is None else claims.username


def _session_revoked(user: User, generation: int) -> bool:
    """Return ``True`` when *generation* is older than the account's current one.

    Deleting the cookie at logout only asks the browser to forget it. The
    signed token stays good for its full 8 hours, so a copy taken from a
    shared operations-room terminal outlived the operator who signed out, and
    a password change left the sessions it was meant to answer untouched.

    This was first written as a timestamp comparison and could not be made
    correct. itsdangerous records a token's issue time to the WHOLE SECOND, so
    a sign-in in the same second as the logout before it produces a token that
    is byte-for-byte identical to the one being revoked: no comparison of
    clocks can accept the new one and refuse the old, because they are the
    same string. It also made the integration suite fail about half the time,
    which is how it was found. A counter has no resolution to run out of.
    """
    return generation < (user.session_generation or 0)


def _bound_to(user: User, claims: SessionClaims) -> bool:
    """Return ``True`` when the token was issued to this account, not a namesake."""
    return (
        claims.user_id is not None
        and claims.user_id == user.id
        and claims.nonce == (user.session_nonce or "")
        and not _session_revoked(user, claims.generation)
    )


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def require_login(
    request: Request,
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
    username = claims.username

    result = await db.execute(select(User).where(User.username == username))
    user: User | None = result.scalar_one_or_none()
    if user is None:
        logger.warning("Session for unknown user: %s", log_safe(username))
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    if not _bound_to(user, claims):
        logger.info(
            "Refused a session ended by logout or password change, or issued to a deleted namesake: %s",
            log_safe(username),
        )
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )

    user.session_key = claims.key
    request.state.session_current = True
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
    request: Request,
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

    result = await db.execute(select(User).where(User.username == claims.username))
    user: User | None = result.scalar_one_or_none()
    # A session ended by logout or a password change must read as anonymous
    # here too, or the console greets the operator by name on the public page
    # after they have signed out of it.
    if user is None or not _bound_to(user, claims):
        return None
    user.session_key = claims.key
    request.state.session_current = True
    return user
