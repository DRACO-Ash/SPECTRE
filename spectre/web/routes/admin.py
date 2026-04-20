"""Admin user management routes for SPECTRE web console."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.web.auth import hash_password, require_admin
from spectre.web.database import get_db
from spectre.web.deps import get_templates, render
from spectre.web.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

_VALID_ROLES = {"operator", "admin"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _table_response(
    request: Request,
    users: list[User],
    current_user: User,
    flash: dict[str, str] | None = None,
) -> HTMLResponse:
    """Return tbody rows + OOB flash update as a single HTMX response."""
    tmpl = get_templates()
    ctx: dict[str, Any] = {"users": users, "current_user": current_user, "request": request}
    table_html = tmpl.get_template("partials/admin_user_table.html").render(ctx)
    flash_html = tmpl.get_template("partials/admin_flash.html").render({"flash": flash, "request": request})
    return HTMLResponse(table_html + flash_html)


def _row_response(
    request: Request,
    user: User,
    current_user: User,
    flash: dict[str, str] | None = None,
) -> HTMLResponse:
    """Return a single display row + OOB flash update."""
    tmpl = get_templates()
    ctx: dict[str, Any] = {"u": user, "current_user": current_user, "request": request}
    row_html = tmpl.get_template("partials/admin_user_row.html").render(ctx)
    flash_html = tmpl.get_template("partials/admin_flash.html").render({"flash": flash, "request": request})
    return HTMLResponse(row_html + flash_html)


async def _all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def _admin_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    return result.scalar_one()


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Render the full user management page."""
    users = await _all_users(db)
    return render(request, "admin/users.html", {
        "users": users,
        "current_user": current_user,
        "flash": None,
    })


@router.post("/users", response_class=HTMLResponse)
async def create_user(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Create a new user; return the updated tbody rows via HTMX."""
    username = username.strip()

    if role not in _VALID_ROLES:
        error = "Invalid role selected."
    elif not username:
        error = "Username is required."
    elif len(username) > 64:
        error = "Username must be 64 characters or fewer."
    elif not password:
        error = "Password is required."
    else:
        existing = await db.execute(select(User).where(User.username == username))
        error = f"Username '{username}' is already taken." if existing.scalar_one_or_none() else None

    users = await _all_users(db)
    if error:
        return _table_response(request, users, current_user, flash={"type": "error", "message": error})

    new_user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(new_user)
    await db.commit()
    logger.info("Admin '%s' created user '%s' (role=%s)", current_user.username, username, role)

    users = await _all_users(db)
    return _table_response(
        request, users, current_user,
        flash={"type": "success", "message": f"User '{username}' created."},
    )


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_row(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Return the inline edit row for a user (HTMX outerHTML swap)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return HTMLResponse("<tr><td colspan='5'>User not found.</td></tr>", status_code=404)
    tmpl = get_templates()
    html = tmpl.get_template("partials/admin_user_edit_row.html").render({
        "u": user, "current_user": current_user, "request": request,
    })
    return HTMLResponse(html)


@router.get("/users/{user_id}/cancel", response_class=HTMLResponse)
async def cancel_edit_row(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Cancel inline edit — return the display row (HTMX outerHTML swap)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return HTMLResponse("<tr><td colspan='5'>User not found.</td></tr>", status_code=404)
    tmpl = get_templates()
    html = tmpl.get_template("partials/admin_user_row.html").render({
        "u": user, "current_user": current_user, "request": request,
    })
    return HTMLResponse(html)


@router.post("/users/{user_id}", response_class=HTMLResponse)
async def update_user(
    request: Request,
    user_id: int,
    role: Annotated[str, Form()],
    new_password: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Save role change and optional password reset (HTMX outerHTML swap)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return HTMLResponse("<tr><td colspan='5'>User not found.</td></tr>", status_code=404)

    if role not in _VALID_ROLES:
        return _row_response(request, user, current_user, flash={"type": "error", "message": "Invalid role."})

    # Guard: cannot demote the last admin
    if user.role == "admin" and role != "admin":
        admin_count = await _admin_count(db)
        if admin_count <= 1:
            return _row_response(
                request, user, current_user,
                flash={"type": "error", "message": "Cannot demote the last admin account."},
            )

    changed: list[str] = []
    if user.role != role:
        user.role = role
        changed.append("role")

    if new_password:
        user.hashed_password = hash_password(new_password)
        changed.append("password")

    if changed:
        await db.commit()
        logger.info(
            "Admin '%s' updated user '%s': %s",
            current_user.username, user.username, ", ".join(changed),
        )

    label = " and ".join(changed) if changed else "no changes"
    return _row_response(
        request, user, current_user,
        flash={"type": "success", "message": f"User '{user.username}' updated ({label})."},
    )


@router.delete("/users/{user_id}", response_class=HTMLResponse)
async def delete_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Delete a user; return the updated tbody rows via HTMX."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        users = await _all_users(db)
        return _table_response(request, users, current_user, flash={"type": "error", "message": "User not found."})

    if user.id == current_user.id:
        users = await _all_users(db)
        return _table_response(
            request, users, current_user,
            flash={"type": "error", "message": "You cannot delete your own account."},
        )

    if user.role == "admin":
        admin_count = await _admin_count(db)
        if admin_count <= 1:
            users = await _all_users(db)
            return _table_response(
                request, users, current_user,
                flash={"type": "error", "message": "Cannot delete the last admin account."},
            )

    username = user.username
    await db.delete(user)
    await db.commit()
    logger.info("Admin '%s' deleted user '%s'", current_user.username, username)

    users = await _all_users(db)
    return _table_response(
        request, users, current_user,
        flash={"type": "success", "message": f"User '{username}' deleted."},
    )
