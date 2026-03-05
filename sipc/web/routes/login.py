"""Login / logout routes for SIPC web console."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sipc.web.auth import _COOKIE_NAME, make_session_cookie, verify_password
from sipc.web.database import get_db
from sipc.web.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _templates() -> object:
    """Import templates lazily to avoid circular import at module load."""
    from sipc.web.app import templates  # noqa: PLC0415

    return templates


@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request) -> HTMLResponse:
    """Render the login page."""
    tmpl = _templates()
    return tmpl.TemplateResponse("login.html", {"request": request, "error": None})  # type: ignore[attr-defined]


@router.post("/login", response_model=None)
async def post_login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    """Authenticate and set a session cookie, or re-render with an error."""
    tmpl = _templates()

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.hashed_password):
        logger.warning("Failed login attempt for username: %s", username)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )

    logger.info("Successful login: %s (role=%s)", username, user.role)
    token = make_session_cookie(username)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=28_800,
    )
    return response


@router.post("/logout", response_model=None)
async def post_logout(request: Request) -> RedirectResponse:
    """Clear the session cookie, disconnect STK, wipe planning state, then redirect."""
    from sipc.web.auth import decode_session_cookie  # noqa: PLC0415
    from sipc.web.planning_state import clear_session_state, get_session_state  # noqa: PLC0415

    cookie = request.cookies.get(_COOKIE_NAME)
    if cookie:
        username = decode_session_cookie(cookie)
        if username:
            state = get_session_state(username)
            if state.stk_session is not None:
                try:
                    state.stk_session.disconnect()
                except Exception:
                    pass
            clear_session_state(username)
            logger.info("Session state cleared on logout for: %s", username)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=_COOKIE_NAME)
    return response
