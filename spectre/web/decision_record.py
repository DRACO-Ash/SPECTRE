"""The durable decision record (SPC-192, evaluation F-01): one row per finished evaluation, and the operator's decision.

A finished evaluation was held only in session memory and logged as one line, so once the sign-in ended nothing
showed what the operator was recommended, chose or rejected. Each evaluation that finishes now writes a
DecisionRecord (spectre.web.models): when, who, the scenario, the rule used and its pick, the picks of all three
rules on the same matrix, the code version and every input hash, the turns and the keep-out distance. The results
page then asks for the operator's decision, which a record accepts once, from the operator who ran it.

The three rules' picks are the engine's own find_robust_response on the result's matrix, read and never written:
no figure and no recommendation changes. No element-set text and no raw input is stored; replay is SPC-193.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.domain.decision import FriendlyResponse, ScenarioResult, SelectorStrategy, find_robust_response
from spectre.web.log_safety import log_safe
from spectre.web.models import DecisionRecord, User

logger = logging.getLogger(__name__)

#: The three rules, in the order every record and page lists them.
RULES: tuple[SelectorStrategy, ...] = (
    SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE,
)


#: The two decisions that are not one of the scenario's responses, by the value the select posts.
NONE_OF_THESE = "none"
DEFERRED = "deferred"
_NOT_A_RESPONSE: dict[str, str] = {NONE_OF_THESE: "None of these", DEFERRED: "Decision deferred"}
#: A response's value on the select: its place among the scenario's responses, so two rows sharing an id differ.
_RESPONSE_VALUE = "response-{n}"
#: The longest rationale a record takes, in characters.
MAX_RATIONALE = 2000
#: Shown in place of the decision form when the record could not be written.
UNRECORDED = (
    "This evaluation finished, but its decision record could not be written; the server log has the detail. "
    "No decision can be recorded against it."
)
# Why a decision is refused, each a fixed sentence. A record that is not the operator's is refused as one that does
# not exist, so another operator's record numbers cannot be told from unused ones.
_NOT_YOURS = "No decision record of yours has that number."
_ONCE = "A decision is already recorded for this evaluation; a record takes one decision, once."
_CHOOSE = "Choose one of the listed decisions."
_TOO_LONG = "The rationale is at most {most:,} characters; this one is {n:,}."
_SAY_WHY = "Give the rationale: it is required when none of these responses is chosen."
_CONTROL = "The rationale holds a control character, which a record cannot store; remove it and record again."
#: A control character other than tab, line feed and carriage return: PostgreSQL's text refuses U+0000, which
#: SQLite stores, and no other has a place in a typed rationale.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
#: What a record keeps in place of U+0000 in a name, which PostgreSQL's text cannot store: the replacement character.
_UNSTORABLE, _REPLACEMENT = "\x00", "\ufffd"


@dataclass(frozen=True)
class Operator:
    """Who ran an evaluation: the account's id and the name it signed in with."""

    user_id: int
    username: str


def rule_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse]:
    """Each rule's pick on *result*'s matrix, by find_robust_response; nothing on *result* is changed."""
    return {rule: find_robust_response(result.scenario, result.outcome_matrix, rule) for rule in RULES}


def _hashes(result: ScenarioResult) -> list[dict[str, str | None]]:
    """Every input hash in *result*'s provenance, in its order; none when it carries no provenance."""
    if result.provenance is None:
        return []
    return [
        {"label": ref.label, "sha256": ref.sha256, "epoch": None if ref.epoch is None else ref.epoch.isoformat()}
        for ref in result.provenance.inputs
    ]


def _sessions() -> AsyncSession:
    """A session on the application's database, read when called so the engine a test configures is the one used."""
    from spectre.web import database

    return database.AsyncSessionLocal()


async def write_record(result: ScenarioResult, operator: Operator) -> int | None:
    """Write the record of *result*, run by *operator*, finished now; its id, or None when it could not be written.

    A write that fails is logged with its traceback and answered None, so the operator still sees the results they
    waited for and the page says plainly that no record, and so no decision, is held for them.

    The record is written only while the account that ran it still exists under that name, checked in the same
    transaction as the write: an evaluation that finishes after its account was deleted would otherwise carry the
    freed id, which SQLite hands to the next account created.
    """
    try:
        async with _sessions() as db:
            row = new_record(result, operator, datetime.now(UTC))
            db.add(row)
            await db.flush()
            if not await _account_exists(db, operator):
                await db.rollback()
                logger.warning(
                    "Decision record for %s not written: account %s no longer exists",
                    log_safe(result.scenario.name), log_safe(operator.username),
                )
                return None
            await db.commit()
            return row.id
    except Exception:
        logger.exception("Decision record for %s could not be written", log_safe(result.scenario.name))
        return None


async def _account_exists(db: AsyncSession, operator: Operator) -> bool:
    """Whether *operator*'s account is still held, under the id and the name it ran the evaluation with."""
    found = await db.execute(select(User.id).where(User.id == operator.user_id, User.username == operator.username))
    return found.first() is not None


def _kept(text: str) -> str:
    """*text* as a record keeps it: U+0000, which PostgreSQL's text refuses and SQLite stores, as U+FFFD."""
    return text.replace(_UNSTORABLE, _REPLACEMENT)


def _tree_pick(result: ScenarioResult) -> FriendlyResponse | None:
    """The tree's own pick for turn 1 under the result's rule; None for one turn, or a tree with no pick."""
    selection = None if result.tree is None else result.tree.selection
    first = None if selection is None or not selection.picks else selection.picks[0].pick
    return None if first is None else result.scenario.friendly_responses[first]


def _tree_lines(result: ScenarioResult) -> list[str]:
    """What the results said of the tree's recommendation: the selection's own lines, or why it has none."""
    tree = result.tree
    if tree is None:
        return []
    return list(tree.lines if tree.selection is None else tree.selection.recommendation)


def expected_value_caveat(result: ScenarioResult) -> str | None:
    """The guidance the results show under expected value when its probability is not earned, whatever rule ran;
    None when it is earned. Read from a copy of *result* under expected value, so nothing on *result* changes."""
    return dataclasses.replace(result, robust_strategy=SelectorStrategy.EXPECTED_VALUE).objective_guidance


def new_record(result: ScenarioResult, operator: Operator, now: datetime) -> DecisionRecord:
    """The record of *result*, run by *operator* and finished at *now*, with no decision yet.

    Every name the operator typed is kept with U+0000 as U+FFFD, so both databases take it alike.
    """
    scenario, provenance = result.scenario, result.provenance
    picks = {rule: (_kept(pick.id), _kept(pick.name)) for rule, pick in rule_picks(result).items()}
    tree_pick, caveat = _tree_pick(result), expected_value_caveat(result)
    return DecisionRecord(
        created_at=now, user_id=operator.user_id, username=operator.username,
        scenario_name=_kept(scenario.name), rule=result.robust_strategy.value,
        recommended_id=_kept(result.robust_best_response.id), recommended_name=_kept(result.robust_best_response.name),
        minimax_id=picks[SelectorStrategy.MINIMAX][0], minimax_name=picks[SelectorStrategy.MINIMAX][1],
        minimin_id=picks[SelectorStrategy.MINIMIN][0], minimin_name=picks[SelectorStrategy.MINIMIN][1],
        expected_value_id=picks[SelectorStrategy.EXPECTED_VALUE][0],
        expected_value_name=picks[SelectorStrategy.EXPECTED_VALUE][1],
        expected_value_caveat=None if caveat is None else _kept(caveat),
        tree_pick_id=None if tree_pick is None else _kept(tree_pick.id),
        tree_pick_name=None if tree_pick is None else _kept(tree_pick.name),
        tree_recommendation=json.dumps([_kept(line) for line in _tree_lines(result)]),
        code_version="" if provenance is None else provenance.code_version,
        calibration_source="" if provenance is None else provenance.calibration_source,
        input_hashes=json.dumps(_hashes(result)),
        responses=json.dumps([{"id": _kept(r.id), "name": _kept(r.name)} for r in scenario.friendly_responses]),
        turns=scenario.turns, keep_out_km=scenario.keep_out_km,
    )


# ── What the page shows of a record ──

def utc_text(moment: datetime | None) -> str:
    """*moment* as the page shows it, in UTC to the second; empty for none.

    SQLite returns a stored time without its zone; every time written here is UTC, so one without a zone is UTC.
    """
    if moment is None:
        return ""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def choices(responses: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
    """The decision select's options, value and label: each response by name and id, then the two that are not."""
    listed = tuple(
        (_RESPONSE_VALUE.format(n=n), f"{response['name']} ({response['id']})") for n, response in enumerate(responses)
    )
    return (*listed, *_NOT_A_RESPONSE.items())


@dataclass(frozen=True)
class RecordView:
    """One record as its decision region shows it: the options to choose from, or the decision already made."""

    id: int
    choices: tuple[tuple[str, str], ...]
    decision_name: str = ""
    rationale: str = ""
    decided_at: str = ""

    @property
    def decided(self) -> bool:
        return bool(self.decided_at)


def fresh_view(record_id: int, result: ScenarioResult) -> RecordView:
    """The view of the record just written for *result*, which holds no decision yet."""
    return RecordView(
        record_id,
        choices([{"id": _kept(r.id), "name": _kept(r.name)} for r in result.scenario.friendly_responses]),
    )


async def stored_view(db: AsyncSession, record_id: int, result: ScenarioResult) -> RecordView:
    """The view of record *record_id* as it is stored now, with its decision once made; as written, should it be
    gone."""
    row = await db.get(DecisionRecord, record_id)
    return fresh_view(record_id, result) if row is None else row_view(row)


def row_view(row: DecisionRecord) -> RecordView:
    """The view of a stored record, with its decision when it holds one."""
    return RecordView(
        row.id, choices(json.loads(row.responses)), row.decision_name or "", row.rationale or "",
        utc_text(row.decided_at),
    )


# ── The operator's decision: once, by the operator who ran the evaluation ──

@dataclass(frozen=True)
class Decided:
    """What a decision post comes to: the record to show, None when it may not be shown, and why it was refused."""

    row: DecisionRecord | None
    problem: str = ""


def _refusal(row: DecisionRecord, decision: str, rationale: str) -> str:
    """Why *decision* with *rationale* cannot be recorded on *row*, checked in order; empty when it can."""
    if row.decided_at is not None:
        return _ONCE
    if decision not in dict(choices(json.loads(row.responses))):
        return _CHOOSE
    if len(rationale) > MAX_RATIONALE:
        return _TOO_LONG.format(most=MAX_RATIONALE, n=len(rationale))
    if _CONTROL_CHARACTER.search(rationale):
        return _CONTROL
    if decision == NONE_OF_THESE and not rationale:
        return _SAY_WHY
    return ""


async def decide(
    db: AsyncSession, record_id: int, operator: Operator, decision: str, rationale: str,
) -> Decided:
    """Record *operator*'s *decision* and *rationale* on record *record_id*, at the time it is stored.

    Only the operator who ran the evaluation may decide it; an admin reads every record but decides only their
    own. A record takes one decision: the write is conditional on the record holding none and still being the
    operator's, so two posts that race record the first and refuse the second, and a record let go of its account
    between the read and the write is refused. The rationale is stored without its surrounding whitespace.
    """
    row = await db.get(DecisionRecord, record_id)
    if row is None or not _owns(row, operator):
        return Decided(None, _NOT_YOURS)
    said = rationale.strip()
    problem = _refusal(row, decision, said)
    if problem:
        return Decided(row, problem)
    taken = await db.execute(
        update(DecisionRecord)
        .where(
            DecisionRecord.id == record_id, DecisionRecord.user_id == operator.user_id,
            DecisionRecord.decided_at.is_(None),
        )
        .values(
            decision=decision, decision_name=dict(choices(json.loads(row.responses)))[decision],
            rationale=said or None, decided_at=datetime.now(UTC),
        )
    )
    await db.commit()
    await db.refresh(row)
    if taken.rowcount:  # type: ignore[attr-defined]
        return Decided(row)
    return Decided(row, _ONCE) if _owns(row, operator) else Decided(None, _NOT_YOURS)


def _owns(row: DecisionRecord, operator: Operator) -> bool:
    """Whether *operator* ran the evaluation *row* records; no one does once its account is deleted."""
    return row.user_id is not None and row.user_id == operator.user_id


# ── The records page ──

async def records_for(db: AsyncSession, operator: Operator, *, every: bool) -> list[DecisionRecord]:
    """*operator*'s records, or every record when *every*, newest first."""
    query = select(DecisionRecord).order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
    if not every:
        query = query.where(DecisionRecord.user_id == operator.user_id)
    return list((await db.execute(query)).scalars().all())


#: Each rule in the words the records page uses.
_RULE_WORDS: dict[str, str] = {rule.value: rule.value.replace("_", " ") for rule in SelectorStrategy}


@dataclass(frozen=True)
class ListedRecord:
    """One record as the records page lists it, every field text the template escapes."""

    id: int
    created: str
    username: str
    scenario_name: str
    rule: str
    recommended: str
    picks: tuple[tuple[str, str], ...]
    turns: int
    keep_out_km: str
    code_version: str
    inputs: int
    decision: RecordView
    #: The tree's turn-1 pick, and what the results said of the tree's recommendation; empty for one turn.
    tree_pick: str
    tree_lines: tuple[str, ...]
    #: Why expected value's pick rests on a probability not earned, as the results would say it; empty when earned.
    caveat: str
    #: Whether the viewer may decide it here: their own record, not yet decided.
    decidable: bool


def as_entered(km: float) -> str:
    """*km* in the fewest digits that give back the number entered: 10 for 10.0, 1234.5678 as itself."""
    return repr(km).removesuffix(".0")


def listed(row: DecisionRecord, viewer: Operator) -> ListedRecord:
    """*row* as the records page lists it to *viewer*."""
    view = row_view(row)
    return ListedRecord(
        id=row.id, created=utc_text(row.created_at), username=row.username, scenario_name=row.scenario_name,
        rule=_RULE_WORDS.get(row.rule, row.rule), recommended=f"{row.recommended_name} ({row.recommended_id})",
        picks=(
            ("minimax", f"{row.minimax_name} ({row.minimax_id})"),
            ("minimin", f"{row.minimin_name} ({row.minimin_id})"),
            ("expected value", f"{row.expected_value_name} ({row.expected_value_id})"),
        ),
        turns=row.turns, keep_out_km=as_entered(row.keep_out_km), code_version=row.code_version or "not recorded",
        inputs=len(json.loads(row.input_hashes)), decision=view,
        tree_pick="" if row.tree_pick_id is None else f"{row.tree_pick_name} ({row.tree_pick_id})",
        tree_lines=tuple(json.loads(row.tree_recommendation)), caveat=row.expected_value_caveat or "",
        decidable=_owns(row, viewer) and not view.decided,
    )
