"""ORM models for the SPECTRE training environment.

These tables are separate from operational data. (Training routes do add
tagged synthetic objects to the operator's session state while a scenario
runs; see spectre.training.)
The isolation boundary:
  - training_* tables ←→ operator progress, scores, session logs
  - users table: read-only reference by account id (``user_id``)

Every training row is keyed on the account id, not the username. Keyed on
the username, a deleted account's progress, attempts and sessions passed to
anyone later created with the same name. The username is still stored, as a
label for whoever reads the table, and is never used to look a row up.
The rows are deleted with the account (routes/admin.py), because SQLite
reuses a freed id and would otherwise hand them to the next account.
  - No access to: session state, operational TLEs, UDL credentials
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from spectre.web.database import Base


class TrainingProgress(Base):
    """Per-operator cumulative training state.

    One row per account.  Updated whenever the operator earns points,
    completes a tutorial, or passes a challenge.
    """

    __tablename__ = "training_progress"

    id:       Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:  Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    # A label, not a key: unique on the account, not the name.
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Totals
    total_points:      Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    current_level:     Mapped[int]   = mapped_column(Integer, default=1, nullable=False)
    scenarios_started: Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    scenarios_passed:  Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    tutorials_done:    Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    challenges_passed: Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    time_in_training_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Skill axis point totals — stored as JSON for flexibility
    # e.g. '{"situational_awareness":120,"manoeuvre_planning":80,...}'
    axis_points_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # Completed tutorial IDs — JSON list of strings
    tutorials_completed_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # Unlocked content IDs — JSON list of strings
    unlocked_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def axis_points(self) -> dict[str, float]:
        try:
            return dict(json.loads(self.axis_points_json))
        except (ValueError, TypeError):
            return {}

    @axis_points.setter
    def axis_points(self, value: dict[str, float]) -> None:
        self.axis_points_json = json.dumps(value)

    @property
    def tutorials_completed(self) -> list[str]:
        try:
            return list(json.loads(self.tutorials_completed_json))
        except (ValueError, TypeError):
            return []

    @tutorials_completed.setter
    def tutorials_completed(self, value: list[str]) -> None:
        self.tutorials_completed_json = json.dumps(value)

    @property
    def unlocked(self) -> list[str]:
        try:
            return list(json.loads(self.unlocked_json))
        except (ValueError, TypeError):
            return []

    @unlocked.setter
    def unlocked(self, value: list[str]) -> None:
        self.unlocked_json = json.dumps(value)


class TrainingSession(Base):
    """One training session — from entering training mode to leaving it."""

    __tablename__ = "training_sessions"

    id:         Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:    Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username:   Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    points_earned_this_session: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scenarios_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ChallengeResult(Base):
    """One scored attempt at a challenge or free-play scenario."""

    __tablename__ = "training_challenge_results"

    id:          Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:     Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username:    Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_num: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    started_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_taken_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    total_score:  Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    passed:       Mapped[bool]  = mapped_column(default=False, nullable=False)
    first_try:    Mapped[bool]  = mapped_column(default=False, nullable=False)
    # scored=False means a free-exploration run — objectives can be ticked but
    # no points are awarded and the attempt_num counter is not incremented.
    scored:       Mapped[bool]  = mapped_column(default=True, nullable=False)

    # Per-axis scores — JSON dict
    axis_scores_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # Objectives completed — JSON list of objective IDs
    objectives_json: Mapped[str]  = mapped_column(Text, default="[]", nullable=False)
    # Debrief notes generated by the scoring engine
    debrief_json: Mapped[str]     = mapped_column(Text, default="{}", nullable=False)

    @property
    def axis_scores(self) -> dict[str, float]:
        try:
            return dict(json.loads(self.axis_scores_json))
        except (ValueError, TypeError):
            return {}

    @axis_scores.setter
    def axis_scores(self, value: dict[str, float]) -> None:
        self.axis_scores_json = json.dumps(value)

    @property
    def objectives_completed(self) -> list[str]:
        try:
            return list(json.loads(self.objectives_json))
        except (ValueError, TypeError):
            return []

    @objectives_completed.setter
    def objectives_completed(self, value: list[str]) -> None:
        self.objectives_json = json.dumps(value)

    @property
    def debrief(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.debrief_json))
        except (ValueError, TypeError):
            return {}

    @debrief.setter
    def debrief(self, value: dict[str, Any]) -> None:
        self.debrief_json = json.dumps(value)


# Every table keyed on an account, deleted with it (routes/admin.py).
TRAINING_TABLES: tuple[type[TrainingProgress] | type[TrainingSession] | type[ChallengeResult], ...] = (
    TrainingProgress, TrainingSession, ChallengeResult,
)
