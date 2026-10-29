"""ORM models for SPECTRE web layer."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import DateTime, Index, Integer, String, event, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.base import NO_VALUE

from spectre.web.database import Base


class SessionKey(NamedTuple):
    """One sign-in: the account and the random id its token was issued with.

    Planning state, and the UDL credentials on it, are filed under this rather
    than the username, so a second sign-in of the same account starts clean
    and nothing outlives the account (audit F-044, F-148).
    """

    user_id: int
    session_id: str


class User(Base):
    """Operator / admin user stored in the auth database.

    Attributes:
        id: Auto-incremented primary key.
        username: Unique login name.
        hashed_password: bcrypt hash of the password; never store plaintext.
        role: ``"operator"`` or ``"admin"``.
        created_at: UTC timestamp of account creation.
        session_nonce: random per-account value stamped into every session
            token, so a recreated namesake cannot accept the old account's.
        session_generation: counter stamped into every session token this
            account mints. Logout and a password change increment it, which
            refuses every token carrying an older value. A counter rather than
            a timestamp because itsdangerous records a token's issue time to
            the WHOLE SECOND, so a logout and the sign-in that follows it
            inside the same second are indistinguishable by clock: the token
            minted after the logout is byte-for-byte the token minted before
            it. No timestamp comparison can accept one and refuse the other.
            Incrementing a counter changes the payload, so the new token is a
            different string and the old one is refused exactly.
    """

    __tablename__ = "users"
    # session_key below is per request, not a column.
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
    # NOT NULL DEFAULT 0 is a CONSTANT default, which SQLite accepts in
    # ALTER TABLE ADD COLUMN, and "INTEGER NOT NULL DEFAULT 0" carries only
    # uppercase letters, digits and spaces, so it satisfies the
    # _SQL_COLUMN_DEFINITION guard in database.py without widening it. A row
    # that predates the column therefore arrives at generation 0, which is
    # where a fresh account starts, so migrated accounts and new ones behave
    # identically and there is no None case to reason about.
    session_generation: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    # A random value set when the account is created and carried in every
    # session token it mints. A deleted and recreated "alice" gets a new one,
    # so the old account's unexpired tokens no longer match even where SQLite
    # hands the new row the old row's id (audit F-048). A row from before the
    # column existed arrives with the empty string, and its tokens carry the
    # same empty string, so it keeps working; any account created after the
    # upgrade is random.
    session_nonce: Mapped[str] = mapped_column(
        String(32),
        default=lambda: secrets.token_hex(16),
        server_default="",
        nullable=False,
    )

    # Set by require_login from the token that authenticated this request.
    session_key: SessionKey | None = None


# One account per name whatever its letter case (SPC-020). A fresh database
# gets this from create_all; an existing one gets it at boot, unless it
# already holds names that differ only in case (database._username_unique).
USERNAME_LOWER_INDEX = "ux_users_username_lower"
Index(USERNAME_LOWER_INDEX, func.lower(User.username), unique=True)


# A password change has to end the sessions that were opened with the old
# password. It did not: a cookie captured beforehand stayed valid for its full
# 8 hours, so the reset answered the theft it was meant to answer in name only.
#
# This is an attribute listener rather than a line in the admin reset handler
# because two places already rewrite a hash - the admin form and the
# break-glass bootstrap in database.py - and a listener cannot be forgotten by
# whoever adds the third. active_history makes SQLAlchemy load the previous
# value before the assignment, so the test below distinguishes "this account
# never had a password" from "the column simply was not loaded".
@event.listens_for(User.hashed_password, "set", active_history=True)
def _revoke_sessions_on_password_change(
    target: User, _value: str, oldvalue: object, _initiator: object
) -> None:
    """Advance *target*'s session generation when its password hash is replaced."""
    if oldvalue is NO_VALUE or not oldvalue:
        # Account creation, or the empty placeholder the break-glass path
        # writes before it hashes: no password means no session can have been
        # opened with one, so there is nothing to revoke.
        return
    target.session_generation = (target.session_generation or 0) + 1
    # Every sign-in it ended loses its planning state too, UDL password
    # included (audit F-148). Deferred: planning_state imports this module.
    if target.id is not None:
        from spectre.web.planning_state import clear_account_state

        clear_account_state(target.id)
