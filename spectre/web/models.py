"""ORM models for SPECTRE web layer."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, event, func
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


class DecisionRecord(Base):
    """One finished Decision Engine evaluation, and what the operator decided on it (SPC-192, evaluation F-01).

    Written when the evaluation finishes, whichever path ran it: when (UTC), who, the scenario's name, the rule
    used and its pick on the one-turn matrix, the picks of all three rules on the same matrix with expected value's
    basis, a tree's own turn-1 pick and recommendation lines, the code version and every input hash from the
    result's provenance, the turns and the keep-out distance. The responses the operator may choose from
    are listed by id and name, so a decision is checked against the scenario's own rows. The decision, its
    rationale and its own UTC time are set once, by the operator who ran the evaluation.

    Since 0.28.0 it also holds the deployment's primary rule and whether the rule used differed (SPC-194), and the
    evaluation's canonical inputs with their SHA-256, element-set text included, so the recommendation can be replayed
    from the record alone (SPC-193, F-02), since SPC-205 the recommendation's weight stability as the results
    said it, and since SPC-207 its training-only label. No retention is applied; how long records are kept and who
    may read them is the owner's decision (SPC-228), and it covers the stored inputs too.

    Only generic types, so the table is the same on SQLite and PostgreSQL. Operator text is Text, never
    String(n): PostgreSQL enforces a length SQLite ignores, so a name one database stored the other would refuse.
    For the same reason a name's U+0000, which PostgreSQL's text refuses, is kept as U+FFFD. The lists are Text
    holding JSON, for the same portability.

    *user_id* is the account that ran it, and None once that account is deleted, so a later account handed the
    same id by SQLite never reads it; *username* keeps the name it was run under, for an admin reading it. Keeping
    a deleted account's records is Claude's design choice, awaiting the owner's ruling as data protection lead.
    """

    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_name: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_id: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_name: Mapped[str] = mapped_column(Text, nullable=False)
    minimax_id: Mapped[str] = mapped_column(Text, nullable=False)
    minimax_name: Mapped[str] = mapped_column(Text, nullable=False)
    minimin_id: Mapped[str] = mapped_column(Text, nullable=False)
    minimin_name: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value_id: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: What the results say under expected value when its probability is not earned, whatever rule ran; None when
    #: it is earned.
    expected_value_caveat: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: For a game tree, the rule's own pick for turn 1, which can differ from the one-turn matrix's; None for one turn
    #: or a tree with no pick.
    tree_pick_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tree_pick_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The tree's recommendation lines as the results showed them, or why it has none, as JSON; [] for one turn.
    tree_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_source: Mapped[str] = mapped_column(Text, nullable=False)
    #: [{"label", "sha256", "epoch"}] in the provenance's order, as JSON.
    input_hashes: Mapped[str] = mapped_column(Text, nullable=False)
    #: [{"id", "name"}] of the scenario's friendly responses, in its order, as JSON; a response marked not permitted
    #: (SPC-195) also carries "not_permitted", its reason.
    responses: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[int] = mapped_column(Integer, nullable=False)
    keep_out_km: Mapped[float] = mapped_column(Float, nullable=False)
    #: The response's place in *responses* as "response-<n>", "none" or "deferred"; None until decided.
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: What the operator chose, in the words the select showed.
    decision_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The deployment's primary rule when the evaluation ran, SPECTRE_PRIMARY_RULE (SPC-194); "" on a record written
    #: before 0.28.0 set one, which init_db upgrades in place.
    primary_rule: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    #: Whether the rule used differed from the primary rule; None on a record written before 0.28.0.
    rule_differed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: The evaluation's canonical inputs (SPC-193, evaluation F-02): the whole scenario, element-set text included, the
    #: rule and the composite scores, as canonical JSON (spectre.domain.decision_inputs), and its SHA-256. None on a
    #: record written before 0.28.0, which cannot be replayed.
    inputs: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The recommendation's weight stability as the results said it (SPC-205, evaluation F-16): the overall smallest
    #: change of one weight that changes the primary rule's pick on the one-turn matrix, or why there is none to show.
    #: None on a record written before it was recorded, which init_db upgrades in place.
    weight_stability: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The training-only label as the results showed it (SPC-207, evaluation F-17), naming each unsourced relation of
    #: the lookup model the result rests on; "" when it rests on none. None on a record written before it was
    #: recorded, which init_db upgrades in place.
    training_only: Mapped[str | None] = mapped_column(Text, nullable=True)
