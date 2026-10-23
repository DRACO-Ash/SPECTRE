"""Login / logout routes for SPECTRE web console."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from spectre.config.settings import get_settings
from spectre.web.auth import _COOKIE_NAME, hash_password, make_session_cookie, verify_password
from spectre.web.database import get_db
from spectre.web.deps import render
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.rate_limit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

router = APIRouter()

# Session lifetime in seconds (8 hours), matching auth._SESSION_MAX_AGE.
_SESSION_COOKIE_MAX_AGE = 28_800

# 10 failed attempts per source address per 300 s. This is the console's only
# unauthenticated credential endpoint and it is CSRF-exempt, so until this
# guard existed 40 consecutive wrong passwords from one address answered 40 x
# 401 and nothing ever answered 429: a password list could be walked at the
# speed of the network.
#
# Only FAILURES are metered. An operations room reaches the console from one
# source address and a shift change puts 12 legitimate sign-ins through it
# inside a minute; charging those against the same budget would lock the room
# out of its own console, which is a worse outage than the attack. A brute
# force is made of failures, so failures are what is counted.
_LOGIN_ADDRESS_LIMITER = SlidingWindowLimiter(max_calls=10, window_seconds=300)

# The second tier, and the one that actually stops a brute force.
#
# The address tier alone is decorative against anyone who sets the header.
# Measured against this application: 25 failed sign-ins with X-Forwarded-For
# rotated per request produced 25 x 401 and not one 429, while 25 from a fixed
# address produced 10 x 401 then 15 x 429. An attacker chooses the key the
# address tier is counting, so the address tier cannot bound them.
#
# A brute force is a search over PASSWORDS for ONE account, so the account is
# the thing to meter. Rotating the header no longer buys anything: ten wrong
# passwords against a given username in five minutes is the ceiling however
# many addresses they are spread across.
#
# Two consequences, both deliberate:
#
# ● The submitted username is metered whether or not the account exists. If
#   only real accounts were counted, a 429 would mean "this name is real" and
#   the enumeration oracle closed above would reopen as a status code.
# ● Someone who knows an operator's username can keep that one account locked
#   for five minutes at a time. That is a bounded nuisance against an
#   unbounded password search, and the break-glass admin path does not go
#   through this endpoint. It is the right way round, but it IS a trade and it
#   is recorded here rather than discovered later.
_LOGIN_USERNAME_LIMITER = SlidingWindowLimiter(max_calls=10, window_seconds=300)

# Username enumeration (CWE-204). "user is None or not verify_password(...)"
# short-circuits, so an unknown name never reached bcrypt and the endpoint
# answered it in 2.6 ms against 270.2 ms for a name that exists. A 103x gap is
# a clean read-out of which operators the system knows, however generic the
# error text is, and an attacker who knows the names has halved the work.
#
# An attempt against an account that does not exist is compared against this
# hash instead, so every attempt does the same bcrypt work. The plaintext is a
# throwaway secret generated at import and never written down anywhere, so no
# submitted password can match it.
_ABSENT_USER_HASH = hash_password(secrets.token_urlsafe(32))


def _client_address(request: Request) -> str:
    """Return the source address the login limiter should charge *request* to.

    Read the same way :func:`spectre.web.app._is_https` reads
    X-Forwarded-Proto: first entry, stripped, falling back to the socket. TLS
    and the client address both terminate at the platform router, so inside
    the container the peer is the router and the forwarded header is the only
    account of who is actually calling. The router rewrites that header, which
    is what stops a caller nominating its own address to get a fresh budget.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    address = forwarded.split(",")[0].strip()
    if address:
        return address
    client = request.client
    return client.host if client else "unknown"


@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request) -> HTMLResponse:
    """Render the login page."""
    return render(request, "login.html", {"error": None})


@router.post("/login", response_model=None)
async def post_login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Authenticate and set a session cookie, or re-render with an error."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    # One bcrypt comparison every time, whether or not the account exists, and
    # never on the event loop. bcrypt costs about 270 ms by design; run inline
    # it IS the worker, and 32 concurrent anonymous requests took /healthz
    # from a 0.9 ms median to 833 ms, which is long enough for the platform to
    # mark a pod unready while it is still answering logins correctly. The
    # readiness probe is the first casualty of an attack on this endpoint.
    hashed = user.hashed_password if user is not None else _ABSENT_USER_HASH
    matched = await run_in_threadpool(verify_password, password, hashed)

    if user is None or not matched:
        address = _client_address(request)
        # Both tiers are charged before either is judged, so an attempt always
        # costs both budgets. Short-circuiting on the first would let a caller
        # who has exhausted the address tier keep probing a username for free.
        address_ok = await _LOGIN_ADDRESS_LIMITER.is_allowed(address)
        username_ok = await _LOGIN_USERNAME_LIMITER.is_allowed(username)
        if not (address_ok and username_ok):
            # Both values are caller-supplied, so both are flattened before
            # they reach the log (pythonsecurity:S5145).
            logger.warning(
                "Login rate limit reached: address=%s username=%s",
                log_safe(address), log_safe(username),
            )
            # A browser is what reaches this endpoint, so the refusal is the
            # login page carrying an explanation, not a bare JSON body the
            # operator would have to read in the network tab.
            return render(
                request,
                "login.html",
                {"error": "Too many failed sign-in attempts. Wait a few minutes and try again."},
                status_code=429,
            )
        # The only unauthenticated path that writes an operator-supplied value
        # into the audit log, so the only one an attacker can pick freely. A bare
        # %s here lets a newline in the form field forge a second record that
        # reads exactly like a successful login (pythonsecurity:S5145).
        logger.warning("Failed login attempt for username: %s", log_safe(username))
        return render(request, "login.html", {"error": "Invalid username or password."}, status_code=401)

    logger.info("Successful login: %s (role=%s)", log_safe(username), user.role)
    token = make_session_cookie(username, user.session_generation or 0)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,   # not readable from JavaScript
        secure=get_settings().session_cookie_secure,  # HTTPS only unless explicitly opted out
        samesite="lax",
        max_age=_SESSION_COOKIE_MAX_AGE,
    )
    return response


async def _revoke_sessions(db: AsyncSession, username: str) -> None:
    """Advance *username*'s session generation, ending every live session.

    Every session, not only the cookie that asked: the operator signing out of
    a shared terminal has no way to know which other copies of their token are
    still in circulation, and that is the case this control exists for.
    """
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        return
    user.session_generation = (user.session_generation or 0) + 1
    await db.commit()


@router.post("/logout", response_model=None)
async def post_logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Revoke the session, clear the cookie, wipe planning state, then redirect."""
    from spectre.web.auth import decode_session_cookie  # noqa: PLC0415
    from spectre.web.planning_state import clear_session_state  # noqa: PLC0415

    cookie = request.cookies.get(_COOKIE_NAME)
    if cookie:
        username = decode_session_cookie(cookie)
        if username:
            # Deleting the cookie only asks the browser to forget it. The token
            # itself stayed signed and valid for its full 8 hours, so a copy
            # captured before this point still answered 200 from /admin/users.
            # On a shared operations-room terminal logout is the operator's
            # only way to end a session, so it has to end it on the server.
            await _revoke_sessions(db, username)
            clear_session_state(username)
            logger.info("Session state cleared on logout for: %s", log_safe(username))

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=_COOKIE_NAME)
    return response
