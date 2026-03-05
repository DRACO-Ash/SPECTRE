"""ORM models for SIPC web layer."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from sipc.web.database import Base


class User(Base):
    """Operator / admin user stored in the auth database.

    Attributes:
        id: Auto-incremented primary key.
        username: Unique login name.
        hashed_password: bcrypt hash of the password; never store plaintext.
        role: ``"operator"`` or ``"admin"``.
        created_at: UTC timestamp of account creation.
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
