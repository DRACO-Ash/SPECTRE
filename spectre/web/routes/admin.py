"""Admin user management routes for SPECTRE web console."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.training.models import TRAINING_TABLES
from spectre.web.auth import (
    PASSWORD_TOO_LONG,
    USERNAME_PATTERN,
    hash_password,
    password_too_long,
    require_admin,
    username_taken,
)
from spectre.web.database import get_db
from spectre.web.deps import get_templates, render
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import clear_account_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

_VALID_ROLES = {"operator", "admin"}

# Why a charset check and not just a length bound.
#
# A username is written into the audit log by this module, by the login route
# and by the session store, and it is also the stable identity an operator is
# judged by afterwards. str.strip() trims only the ends of a string and the
# 64-character bound only counts characters, so neither touches a newline sat
# in the middle of a name. A 61-character name carrying one was accepted and
# stored, and a single logger.warning about that account then wrote two lines,
# the second of which read exactly like a genuine audit record attributing an
# action to somebody else. log_safe() repairs the log line at the point of
# writing; this pattern stops the forged identity being created at all, which
# is the half of the fix that also protects every sink added in future.
#
# The vocabulary is deliberately wider than any SPECTRE screen needs. The
# bootstrap admin account takes its name from SPECTRE_ADMIN_USER, which this
# repository's own deployments set to values such as "admin", "rescue-admin",
# "smoke_admin" and "testadmin", and an operator identity sourced from a
# directory is commonly an e-mail address. A pattern that rejected any of
# those would stop the application starting rather than merely refuse a form,
# so letters, digits, dot, underscore, at-sign and hyphen are all accepted.
_USERNAME_PATTERN = USERNAME_PATTERN


# ── Helpers ───────────────────────────────────────────────────────────────────


def _table_response(
    request: Request,
    users: list[User],
    current_user: User,
    flash: dict[str, str] | None = None,
) -> HTMLResponse:
    """Return the whole table region plus the out-of-band flash.

    The region is a <table>, not a bare run of <tr>, and that is load-bearing.
    htmx 1.9.12 decides how to parse a response from its first tag: a response
    starting with <tr> is wrapped in <table><tbody> before parsing, at which
    point the HTML parser foster-parents the trailing flash <div> out of the
    table. htmx then handed a non-element to its out-of-band code, which threw
    "e.querySelectorAll is not a function" and abandoned the whole swap. The
    server had already committed the change, so a created or deleted
    user was invisible until the page was reloaded by hand.

    Rooting the response at <div>/<table> keeps the flash a legal sibling and
    keeps the parser off the table path entirely. Every mutating endpoint on
    this page returns this shape for that reason; do not switch one back to a
    bare row to save a few bytes.
    """
    tmpl = get_templates()
    ctx: dict[str, Any] = {"users": users, "current_user": current_user, "request": request}
    table_html = tmpl.get_template("partials/admin_user_table_region.html").render(ctx)
    flash_html = tmpl.get_template("partials/admin_flash.html").render({"flash": flash, "request": request})
    return HTMLResponse(table_html + flash_html)


async def _all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def _admin_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    return result.scalar_one()


def _another_admin_remains() -> Any:
    """SQL condition: more than one admin exists at the moment of the write.

    The read-then-write guard let two admins demoting or deleting each other
    at once each count two and both commit (audit F-149). Evaluated inside
    the UPDATE or DELETE itself, the count is the one the write sees.
    """
    count = select(func.count()).select_from(User).where(User.role == "admin").scalar_subquery()
    return count > 1


async def _lock_admin_rows(db: AsyncSession) -> None:
    """Take row locks on the admin rows where the database has them.

    On PostgreSQL two transactions could otherwise each see the other's admin
    in their own snapshot. SQLite has no row locks and runs one writer at a
    time, so the conditional statement is enough there and this is a no-op.
    """
    if db.get_bind().dialect.name != "sqlite":
        await db.execute(select(User.id).where(User.role == "admin").with_for_update())


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

    error: str | None = None
    if role not in _VALID_ROLES:
        error = "Invalid role selected."
    elif not username:
        error = "Username is required."
    elif len(username) > 64:
        error = "Username must be 64 characters or fewer."
    elif not _USERNAME_PATTERN.fullmatch(username):
        error = (
            "Username may contain only letters, digits, dot, underscore, "
            "at-sign and hyphen."
        )
    elif not password:
        error = "Password is required."
    elif password_too_long(password):
        error = PASSWORD_TOO_LONG
    elif await username_taken(db, username):
        error = f"Username '{username}' is already taken. Usernames ignore letter case."

    users = await _all_users(db)
    if error:
        return _table_response(request, users, current_user, flash={"type": "error", "message": error})

    new_user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(new_user)
    await db.commit()
    # Both names reach the audit log from outside: the acting admin's from the
    # session, the new user's straight from the form (pythonsecurity:S5145).
    logger.info(
        "Admin '%s' created user '%s' (role=%s)",
        log_safe(current_user.username), log_safe(username), log_safe(role),
    )

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


async def _set_role(db: AsyncSession, user: User, role: str) -> bool:
    """Change *user*'s role, refusing to demote the last admin. False if refused."""
    guard = [User.id == user.id]
    if user.role == "admin" and role != "admin":
        await _lock_admin_rows(db)
        guard.append(_another_admin_remains())
    done = await db.execute(update(User).where(*guard).values(role=role).execution_options(synchronize_session=False))
    if done.rowcount == 0:  # type: ignore[attr-defined]
        await db.rollback()
        return False
    user.role = role
    return True


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
        return _table_response(
            request, await _all_users(db), current_user,
            flash={"type": "error", "message": "Invalid role."},
        )

    # Judged before anything changes, so a refused password leaves the role as it was.
    if new_password and password_too_long(new_password):
        return _table_response(
            request, await _all_users(db), current_user,
            flash={"type": "error", "message": PASSWORD_TOO_LONG},
        )

    # Guard: cannot demote the last admin
    if user.role == "admin" and role != "admin":
        admin_count = await _admin_count(db)
        if admin_count <= 1:
            return _table_response(
                request, await _all_users(db), current_user,
                flash={"type": "error", "message": "Cannot demote the last admin account."},
            )

    changed: list[str] = []
    if user.role != role:
        if not await _set_role(db, user, role):
            return _table_response(
                request, await _all_users(db), current_user,
                flash={"type": "error", "message": "Cannot demote the last admin account."},
            )
        changed.append("role")

    if new_password:
        user.hashed_password = hash_password(new_password)
        changed.append("password")

    if changed:
        await db.commit()
        logger.info(
            "Admin '%s' updated user '%s': %s",
            log_safe(current_user.username), log_safe(user.username), ", ".join(changed),
        )

    label = " and ".join(changed) if changed else "no changes"
    return _table_response(
        request, await _all_users(db), current_user,
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
    await _lock_admin_rows(db)
    guard = [User.id == user.id]
    if user.role == "admin":
        guard.append(_another_admin_remains())
    removed = await db.execute(delete(User).where(*guard))
    if removed.rowcount == 0:  # type: ignore[attr-defined]
        await db.rollback()
        return _table_response(
            request, await _all_users(db), current_user,
            flash={"type": "error", "message": "Cannot delete the last admin account."},
        )
    # Its training records go in the same transaction. They are keyed on the
    # account id, and SQLite reuses a freed id, so left behind they would
    # pass to the next account created.
    for table in TRAINING_TABLES:
        await db.execute(delete(table).where(table.user_id == user.id))
    await db.commit()
    # The account's planning state goes with it, UDL password included, so a
    # later account of the same name starts clean (audit F-148).
    clear_account_state(user_id)
    logger.info("Admin '%s' deleted user '%s'", log_safe(current_user.username), log_safe(username))

    users = await _all_users(db)
    return _table_response(
        request, users, current_user,
        flash={"type": "success", "message": f"User '{username}' deleted."},
    )
