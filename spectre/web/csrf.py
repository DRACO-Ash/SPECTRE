"""CSRF protection for SPECTRE.

Token = itsdangerous HMAC of a fixed payload keyed on (SECRET_KEY, session_cookie).
The whole cookie is keyed in, so the same session yields the same token and any
new cookie yields a new one. Login and logout both mint or clear the cookie, so
a token really is invalidated by either, and a token minted before a session
epoch moved forward dies with the cookie it was bound to.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

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
    # The WHOLE cookie, digested. Truncating it to 32 characters stopped short
    # of the signature, which is the only part that differs between two
    # sessions minted moments apart. For a realistic operator name the window
    # ended three characters into the timestamp, and those three encode the
    # high bits of the clock, which hold still for hours: the token therefore
    # outlived logout, came back identical at the next login and was unmoved
    # by the session epoch, which is the opposite of what this module claimed.
    # Digesting keeps the salt a fixed length whatever the cookie is. Every
    # token minted under the old salt stops verifying, so a tab left open
    # across the deploy gets one 403 and recovers on reload.
    digest = hashlib.sha256(session_cookie.encode()).hexdigest()
    return Signer(settings.secret_key, salt=f"spectre-csrf:{digest}")


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


#: The pre-session token that guards POST /login (audit F-151), set by the
#: login page as a cookie and a hidden field.
LOGIN_COOKIE = "spectre_login_csrf"
LOGIN_FIELD = "login_csrf"


def new_login_token() -> str:
    """A fresh token for one rendering of the login page."""
    return secrets.token_urlsafe(32)


async def _require_login_token(request: Request) -> None:
    """Refuse a browser login that did not come from our own login page.

    There is no session yet to bind a token to, so the login page sets a
    random token as a cookie and as a hidden field, and a browser's POST must
    return both, matching. A page on another site can make the browser send
    the cookie but cannot read it to fill the field. Host is never read, so
    the check holds behind a router that rewrites it. A request carrying
    neither Origin nor Referer is not a browser form post and passes.
    """
    if not (request.headers.get("origin") or request.headers.get("referer")):
        return
    cookie = request.cookies.get(LOGIN_COOKIE, "")
    submitted = ""
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type in _FORM_CONTENT_TYPES:
        form = await request.form()
        submitted = str(form.get(LOGIN_FIELD, "") or "")
    if not (cookie and submitted and hmac.compare_digest(cookie, submitted)):
        logger.warning("Login refused: missing or mismatched login token")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login form expired or forged.")


async def require_csrf(request: Request) -> None:
    """Global FastAPI dependency: reject non-safe requests without a valid CSRF token.

    HTMX requests carry the token in X-CSRF-Token (configured via hx-headers on
    <body>). Plain HTML form submissions carry it in a hidden csrf_token field.
    GET/HEAD/OPTIONS/TRACE are exempt. The public /login POST has no session
    to bind a token to, so it is checked against the login page's own token.
    """
    if request.method in _SAFE_METHODS:
        return
    if request.url.path in _EXEMPT_PATHS:
        await _require_login_token(request)
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
            # BLE001: any unreadable body has no token, and the check below then refuses it.
            except Exception:  # noqa: BLE001
                token = ""

    if not verify_csrf_token(session_cookie, token):
        logger.warning("CSRF check failed — method=%s path=%s", request.method, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
