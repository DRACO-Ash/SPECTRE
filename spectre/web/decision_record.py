"""The durable decision record (SPC-192, evaluation F-01): one row per finished evaluation, and the operator's decision.

A finished evaluation was held only in session memory and logged as one line, so once the sign-in ended nothing
showed what the operator was recommended, chose or rejected. Each evaluation that finishes now writes a
DecisionRecord (spectre.web.models): when, who, the scenario, the rule used and its pick, the picks of all three
rules on the same matrix, the code version and every input hash, the turns and the keep-out distance. The results
page then asks for the operator's decision, which a record accepts once, from the operator who ran it.

The three rules' picks are the engine's own find_robust_response on the result's matrix, read and never written:
no figure and no recommendation changes. Since 0.28.0 a record also keeps the deployment's primary rule and whether
the rule used differed (SPC-194), and the evaluation's canonical inputs with their SHA-256, element-set text included
(SPC-193, evaluation F-02), from which replay_record evaluates the scenario again and sets the result against the
record. Since SPC-195 each response a record lists carries its reason when it was marked not permitted, so the
records page says which were and why; no vetoed response is ever held as a pick, and one may be recorded as the
operator's decision only with a rationale. Since SPC-205 a record keeps the recommendation's weight stability as the
results said it, weight_stability's own line, in a column of its own: worked out when the record is written, since
the stored inputs hold the scores but not the figures each score's terms come from, and working them out again would
mean evaluating the scenario again. Since SPC-207 a record keeps the result's training-only label as the results
showed it, naming each unsourced relation of the lookup model the result rests on, or "" when it rests on none; a
record from before holds none, and the records page says so. The label is no input and no pick, so the replay neither
reads nor compares it, and a record from before replays as it did.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.config.settings import get_settings
from spectre.domain.decision import FriendlyResponse, ScenarioResult, SelectorStrategy
from spectre.domain.decision_inputs import InputsRefusedError, StoredInputs, read_inputs, store_inputs
from spectre.domain.decision_replay import Evaluate, Named, Recorded, Replay, input_hashes, replay
from spectre.domain.rule_comparison import RULE_WORDS, RULES, expected_value_caveat, matrix_picks
from spectre.domain.weight_stability import TREE_NOT_COVERED, weight_stability
from spectre.web.log_safety import log_safe
from spectre.web.models import DecisionRecord, User

logger = logging.getLogger(__name__)


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
_SAY_WHY_VETOED = "Give the rationale: it is required when the response chosen was marked not permitted."
#: How the decision select labels a response marked not permitted, and what the decision says of it (SPC-195).
_MARKED = "{label}, marked not permitted"
_WAS_MARKED = "{name} ({id}) was marked not permitted: {reason}"
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


def rule_picks(result: ScenarioResult) -> dict[SelectorStrategy, FriendlyResponse | None]:
    """Each rule's pick on *result*'s matrix: the results page's own, rule_comparison.matrix_picks (SPC-194); None for
    expected value when every row has P 0."""
    return matrix_picks(result)


def _held(pick: FriendlyResponse | None) -> tuple[str, str]:
    """A pick as a record holds it, (id, name) kept; ("", "") for none, which the records page says in words."""
    return ("", "") if pick is None else (_kept(pick.id), _kept(pick.name))


def primary_rule() -> SelectorStrategy:
    """The deployment's primary rule, SPECTRE_PRIMARY_RULE, read now (SPC-194); minimax when it is not set."""
    return SelectorStrategy(get_settings().primary_rule)


def _hashes(result: ScenarioResult) -> list[dict[str, str | None]]:
    """Every input hash in *result*'s provenance, in its order: the replay's own, input_hashes (SPC-193)."""
    return input_hashes(result)


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


def _responses(result: ScenarioResult) -> list[dict[str, str]]:
    """The scenario's responses as a record lists them, by id and name, each marked not permitted with its reason
    (SPC-195); every name and reason kept as a record keeps text."""
    listed_responses = []
    for response in result.scenario.friendly_responses:
        entry = {"id": _kept(response.id), "name": _kept(response.name)}
        if response.vetoed:
            entry["not_permitted"] = _kept(response.veto_reason)
        listed_responses.append(entry)
    return listed_responses


def _tree_lines(result: ScenarioResult) -> list[str]:
    """What the results said of the tree's recommendation: the selection's own lines, or why it has none."""
    tree = result.tree
    if tree is None:
        return []
    return list(tree.lines if tree.selection is None else tree.selection.recommendation)


def new_record(
    result: ScenarioResult, operator: Operator, now: datetime, *, primary: SelectorStrategy | None = None,
) -> DecisionRecord:
    """The record of *result*, run by *operator* and finished at *now*, with no decision yet.

    Every name the operator typed is kept with U+0000 as U+FFFD, so both databases take it alike. *primary* is the
    deployment's primary rule when the evaluation ran, read from the settings when not given (SPC-194).
    """
    scenario, provenance = result.scenario, result.provenance
    primary = primary_rule() if primary is None else primary
    inputs, inputs_sha256 = store_inputs(result)
    found = rule_picks(result)
    picks = {rule: _held(pick) for rule, pick in found.items()}
    # The rule used's pick is the engine's own, unless that rule has no pick: expected value with every row at P 0.
    used = _held(None if found[result.robust_strategy] is None else result.robust_best_response)
    tree_pick, caveat = _tree_pick(result), expected_value_caveat(result)
    return DecisionRecord(
        created_at=now, user_id=operator.user_id, username=operator.username,
        scenario_name=_kept(scenario.name), rule=result.robust_strategy.value,
        recommended_id=used[0], recommended_name=used[1],
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
        responses=json.dumps(_responses(result)),
        turns=scenario.turns, keep_out_km=scenario.keep_out_km,
        primary_rule=primary.value, rule_differed=result.robust_strategy is not primary,
        inputs=inputs, inputs_sha256=inputs_sha256, weight_stability=_kept(weight_stability(result, primary).line),
        training_only=_kept(result.training_only or ""),
    )


# ── Replay from the record alone (SPC-193, evaluation F-02) ──

#: Why a record written before inputs were stored cannot be replayed. No version is named: the running code may not
#: yet carry the number of the release that began storing them.
NO_INPUTS = "This record holds no stored inputs: it was written by a version of SPECTRE that did not store them."


def _pick_of(response_id: str | None, name: str | None) -> Named:
    """A pick as a record holds it; None for none: no tree pick, or a rule with no pick, held as an empty id."""
    return None if not response_id and not name else (response_id or "", name or "")


def recorded_of(row: DecisionRecord) -> Recorded:
    """What *row* holds beside its stored inputs: the rule used's pick, each rule's and a tree's turn-1 pick, its rule
    and code version columns, its input hashes and the deployment's primary rule, None when it holds none."""
    primary = next((rule for rule in RULES if rule.value == row.primary_rule), None)
    return Recorded(
        recommended=_pick_of(row.recommended_id, row.recommended_name),
        picks={rule: _pick_of(getattr(row, f"{rule.value}_id"), getattr(row, f"{rule.value}_name")) for rule in RULES},
        tree_pick=_pick_of(row.tree_pick_id, row.tree_pick_name),
        rule=row.rule, code_version=row.code_version, input_hashes=tuple(json.loads(row.input_hashes)),
        primary=primary,
        not_permitted=tuple((r["id"], r["name"], r["not_permitted"]) for r in _vetoed(row)),
    )


def _vetoed(row: DecisionRecord) -> list[dict[str, str]]:
    """The responses *row* lists as marked not permitted, in order; none on a record from before vetoes (SPC-195)."""
    return [r for r in json.loads(row.responses) if "not_permitted" in r]


def stored_of(row: DecisionRecord) -> StoredInputs:
    """*row*'s stored inputs, read strictly; InputsRefusedError when it holds none or the reader refuses them."""
    if row.inputs is None:
        raise InputsRefusedError(NO_INPUTS)
    return read_inputs(row.inputs, row.inputs_sha256 or "")


def replay_record(
    row: DecisionRecord, *, stored: StoredInputs | None = None, evaluate: Evaluate | None = None,
    running: str | None = None,
) -> Replay:
    """Rebuild *row*'s scenario from its stored inputs, evaluate it again under its stored rule, and set the result
    against the record; InputsRefusedError when it holds no inputs or the strict reader refuses them. *stored* is
    stored_of(row) when the caller has read it already, to say what it holds before evaluating.

    Names are compared as the record keeps them, with U+0000 as U+FFFD, so a name holding one compares alike.
    """
    inputs = stored_of(row) if stored is None else stored
    return replay(inputs, recorded_of(row), evaluate=evaluate, running=running, kept=_kept)


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
    """The decision select's options, value and label: each response by name and id, saying when it was marked not
    permitted (SPC-195), then the two that are not responses."""
    listed = tuple((_RESPONSE_VALUE.format(n=n), _choice(response)) for n, response in enumerate(responses))
    return (*listed, *_NOT_A_RESPONSE.items())


def _choice(response: dict[str, str]) -> str:
    label = f"{response['name']} ({response['id']})"
    return _MARKED.format(label=label) if "not_permitted" in response else label


def _marked(responses: list[dict[str, str]], decision: str | None) -> str:
    """What the decision *decision* says when it chose a response marked not permitted: which, and why; else empty."""
    chosen = next(
        (r for n, r in enumerate(responses) if _RESPONSE_VALUE.format(n=n) == decision and "not_permitted" in r), None,
    )
    if chosen is None:
        return ""
    return _WAS_MARKED.format(name=chosen["name"], id=chosen["id"], reason=chosen["not_permitted"])


@dataclass(frozen=True)
class RecordView:
    """One record as its decision region shows it: the options to choose from, or the decision already made."""

    id: int
    choices: tuple[tuple[str, str], ...]
    decision_name: str = ""
    rationale: str = ""
    decided_at: str = ""
    #: When the decision chose a response marked not permitted, which and why (SPC-195); else empty.
    marked: str = ""

    @property
    def decided(self) -> bool:
        return bool(self.decided_at)


def fresh_view(record_id: int, result: ScenarioResult) -> RecordView:
    """The view of the record just written for *result*, which holds no decision yet."""
    return RecordView(record_id, choices(_responses(result)))


async def stored_view(db: AsyncSession, record_id: int, result: ScenarioResult) -> RecordView:
    """The view of record *record_id* as it is stored now, with its decision once made; as written, should it be
    gone."""
    row = await db.get(DecisionRecord, record_id)
    return fresh_view(record_id, result) if row is None else row_view(row)


def row_view(row: DecisionRecord) -> RecordView:
    """The view of a stored record, with its decision when it holds one."""
    responses = json.loads(row.responses)
    return RecordView(
        row.id, choices(responses), row.decision_name or "", row.rationale or "", utc_text(row.decided_at),
        _marked(responses, row.decision),
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
    responses = json.loads(row.responses)
    if decision not in dict(choices(responses)):
        return _CHOOSE
    if len(rationale) > MAX_RATIONALE:
        return _TOO_LONG.format(most=MAX_RATIONALE, n=len(rationale))
    if _CONTROL_CHARACTER.search(rationale):
        return _CONTROL
    if decision == NONE_OF_THESE and not rationale:
        return _SAY_WHY
    if _marked(responses, decision) and not rationale:
        return _SAY_WHY_VETOED
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


#: Each rule in the words the records page uses, by the value a record stores.
_RULE_WORDS: dict[str, str] = {rule.value: words for rule, words in RULE_WORDS.items()}
#: What the records page says of the primary rule (SPC-194): its pick was the recommendation shown, whether the rule
#: used was the same rule or not; no recommendation when it had no pick; or none recorded. No version is named: the
#: running code may not yet carry the number of the release that began recording it.
_PRIMARY_USED = "Primary rule: {primary}, the rule used; {shown}"
_PRIMARY_DIFFERED = "Primary rule: {primary}; {shown} The rule used, {rule}, differed from it."
_SHOWN = "the recommendation shown was its pick, {pick}."
_SHOWN_NONE = "it had no pick, {why}, so no recommendation was shown."
_PRIMARY_UNRECORDED = (
    "Primary rule: not recorded; this record was written by a version of SPECTRE that did not record one."
)
#: Why a record holds a pick as none: expected value's, with every row at P 0, or every rule's, with every response
#: marked not permitted (SPC-195).
_WHY_P0 = "since every row had P 0"
_WHY_VETOED = "since every response was marked not permitted"
#: Each response a record lists as marked not permitted, with its reason (SPC-195).
_NOT_PERMITTED = "Not permitted: {name} ({id}): {reason}"
#: The recommendation's weight stability as the record holds it (SPC-205), and what a record from before says.
_STABILITY = "Weight stability: {line}"
NO_STABILITY = (
    "Weight stability: not recorded; this record was written by a version of SPECTRE that did not record it."
)
#: What the records page says of a record resting on no unsourced relation of the lookup model, and of one written
#: before the label was recorded (SPC-207); a record resting on any shows its label as the results did.
SOURCED_RELATIONS = "Rests on no unsourced relation of the lookup model."
NO_TRAINING_LABEL = (
    "Training-only label: not recorded (this record predates it): it was written by a version of SPECTRE that did "
    "not record whether its result rests on an unsourced relation of the lookup model."
)
#: The rule used and its pick, on a record that holds a primary rule, whose results named the primary's pick the
#: recommendation; and on one from before, whose results recommended the rule used's pick alone.
_USED = "Rule used: {rule}, picking {pick}."
_USED_NONE = "Rule used: {rule}, with no pick, {why}."
_USED_TREE = "Rule used: {rule}; on the one-turn matrix it picks {pick}."
_USED_BEFORE = "Rule used: {rule}. Recommended: {pick}."
_USED_BEFORE_TREE = "Rule used: {rule}. The one-turn matrix recommends {pick}."


@dataclass(frozen=True)
class ListedRecord:
    """One record as the records page lists it, every field text the template escapes."""

    id: int
    created: str
    username: str
    scenario_name: str
    rule: str
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
    #: The deployment's primary rule when it ran, its pick, and whether the rule used differed (SPC-194).
    primary: str
    #: The rule used and its pick, in the words that fit what the results showed when it ran.
    used: str
    #: Each response marked not permitted, with its reason (SPC-195); empty when none was.
    not_permitted: tuple[str, ...] = ()
    #: The recommendation's weight stability as the results said it, or that the record holds none (SPC-205).
    stability: str = NO_STABILITY
    #: The training-only label as the results showed it, that the result rests on no unsourced relation of the lookup
    #: model, or that the record holds neither (SPC-207).
    training_only: str = NO_TRAINING_LABEL

    @property
    def training(self) -> bool:
        """Whether the record says its result is for training only, so the page marks it so."""
        return self.training_only not in (SOURCED_RELATIONS, NO_TRAINING_LABEL)

    @property
    def primary_recorded(self) -> bool:
        """Whether the record holds a primary rule: one written since 0.28.0, whose results showed all three picks."""
        return self.primary != _PRIMARY_UNRECORDED

    @property
    def tree_not_covered(self) -> str | None:
        """For a record of more than one turn that holds a weight stability, that the game tree's picks are not
        covered by it, as the results said (SPC-205); None otherwise."""
        return TREE_NOT_COVERED if self.turns > 1 and self.stability != NO_STABILITY else None


def as_entered(km: float) -> str:
    """*km* in the fewest digits that give back the number entered: 10 for 10.0, 1234.5678 as itself."""
    return repr(km).removesuffix(".0")


def _why_none(row: DecisionRecord) -> str:
    """Why *row* holds a pick as none: every response marked not permitted, else every row at P 0."""
    responses = json.loads(row.responses)
    return _WHY_VETOED if responses and len(_vetoed(row)) == len(responses) else _WHY_P0


def _pick_text(response_id: str, name: str, why: str) -> str:
    """A pick a record holds, as the records page names it: its name and id, or that there was none and *why*."""
    return f"nothing, {why}" if not response_id and not name else f"{name} ({response_id})"


def _primary_text(row: DecisionRecord) -> str:
    """What the records page says of *row*'s primary rule: its pick, the recommendation shown, or that it had none,
    and whether the rule used differed from it."""
    if row.primary_rule not in _RULE_WORDS:
        return _PRIMARY_UNRECORDED
    pick = _pick_of(getattr(row, f"{row.primary_rule}_id"), getattr(row, f"{row.primary_rule}_name"))
    words = {
        "primary": _RULE_WORDS[row.primary_rule],
        "shown": _SHOWN_NONE.format(why=_why_none(row)) if pick is None else _SHOWN.format(pick=f"{pick[1]} ({pick[0]})"),
    }
    if row.primary_rule == row.rule:
        return _PRIMARY_USED.format(**words)
    return _PRIMARY_DIFFERED.format(**words, rule=_RULE_WORDS.get(row.rule, row.rule))


def _used_text(row: DecisionRecord) -> str:
    """The rule used and its pick: since a record holds a primary rule, the primary's pick was the recommendation, so
    the rule used's is only its pick; on a record from before, it was the recommendation."""
    rule, pick = _RULE_WORDS.get(row.rule, row.rule), _pick_of(row.recommended_id, row.recommended_name)
    said = _pick_text(row.recommended_id, row.recommended_name, _why_none(row))
    if row.primary_rule not in _RULE_WORDS:
        return (_USED_BEFORE_TREE if row.turns > 1 else _USED_BEFORE).format(rule=rule, pick=said)
    if pick is None:
        return _USED_NONE.format(rule=rule, why=_why_none(row))
    return (_USED_TREE if row.turns > 1 else _USED).format(rule=rule, pick=said)


def listed(row: DecisionRecord, viewer: Operator) -> ListedRecord:
    """*row* as the records page lists it to *viewer*."""
    view, why = row_view(row), _why_none(row)
    return ListedRecord(
        id=row.id, created=utc_text(row.created_at), username=row.username, scenario_name=row.scenario_name,
        rule=_RULE_WORDS.get(row.rule, row.rule),
        picks=tuple(
            (RULE_WORDS[rule], _pick_text(getattr(row, f"{rule.value}_id"), getattr(row, f"{rule.value}_name"), why))
            for rule in RULES
        ),
        turns=row.turns, keep_out_km=as_entered(row.keep_out_km), code_version=row.code_version or "not recorded",
        inputs=len(json.loads(row.input_hashes)), decision=view,
        tree_pick="" if row.tree_pick_id is None else f"{row.tree_pick_name} ({row.tree_pick_id})",
        tree_lines=tuple(json.loads(row.tree_recommendation)), caveat=row.expected_value_caveat or "",
        decidable=_owns(row, viewer) and not view.decided, primary=_primary_text(row), used=_used_text(row),
        not_permitted=tuple(
            _NOT_PERMITTED.format(name=r["name"], id=r["id"], reason=r["not_permitted"]) for r in _vetoed(row)
        ),
        stability=NO_STABILITY if row.weight_stability is None else _STABILITY.format(line=row.weight_stability),
        training_only=training_text(row.training_only),
    )


def training_text(label: str | None) -> str:
    """What the records page and scripts/replay_decision.py say of a record's training-only label (SPC-207): the
    label, that there is none to give, or that none was recorded."""
    if label is None:
        return NO_TRAINING_LABEL
    return label or SOURCED_RELATIONS
