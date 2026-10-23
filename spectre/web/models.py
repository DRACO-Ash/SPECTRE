"""ORM models for SPECTRE web layer."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, event
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.base import NO_VALUE

from spectre.web.database import Base


def _session_epoch_default() -> datetime:
    """Return the creation instant, truncated to whole seconds.

    The epoch is weighed against the issue time itsdangerous signs into a
    session token, and that stamp carries whole seconds only. A creation
    instant with microseconds on it is therefore a hair LATER than the second
    stamped into the very first token the account mints, which would make a
    brand new operator's first authenticated request look like a session that
    had already been revoked. Truncating gives away precision in the one
    direction that cannot refuse a legitimate session.
    """
    return datetime.now(tz=UTC).replace(microsecond=0)


class User(Base):
    """Operator / admin user stored in the auth database.

    Attributes:
        id: Auto-incremented primary key.
        username: Unique login name.
        hashed_password: bcrypt hash of the password; never store plaintext.
        role: ``"operator"`` or ``"admin"``.
        created_at: UTC timestamp of account creation.
        session_epoch: UTC instant before which session tokens for this account
            are refused. Starts at the creation time and moves forward on
            logout and on a password change. ``None`` on rows written before
            the column existed, which means nothing has ever been revoked.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
    # Nullable because the additive migration cannot fill it in: SQLite refuses
    # ALTER TABLE ADD COLUMN NOT NULL with a non-constant default such as
    # CURRENT_TIMESTAMP, and a literal timestamp needs hyphens and colons,
    # which _SQL_COLUMN_DEFINITION in database.py deliberately excludes. A row
    # that predates the column has revoked nothing, so NULL says exactly that.
    session_epoch: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=_session_epoch_default,
        nullable=True,
    )


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
    """Move *target*'s session epoch to now when its password hash is replaced."""
    if oldvalue is NO_VALUE or not oldvalue:
        # Account creation, or the empty placeholder the break-glass path
        # writes before it hashes: no password means no session can have been
        # opened with one, so there is nothing to revoke. Stamping the epoch
        # here would also overwrite the whole-second creation default with a
        # microsecond value and refuse the account's own first token.
        return
    target.session_epoch = datetime.now(tz=UTC)
