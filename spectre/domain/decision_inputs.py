"""Decision Engine: an evaluation's canonical inputs, written and read strictly (SPC-193, evaluation F-02).

Provenance hashed every input and stored none, so once the sign-in ended a recommendation could not be reproduced.
A decision record now keeps one JSON document holding:

● the whole Scenario: its rows, responses, weights, horizon, turns, keep-out distance and observation; every
  hypothesis with its dispersions and seed; each accepted NOTSO prior; the threat picture; and the binding, with each
  bound element set's text, epoch, age, limit, data mode and custody;
● the rule the evaluation ran under, the result's composite score matrix and the code version that computed it;
● whether its time budget ran out, which a replay, run in full, cannot repeat, so it says so.

Version 2 (SPC-195) adds each response's veto and reason. Version 1, written by 0.28.0, holds neither and is still
read, every response permitted, exactly as a 0.28.0 scenario was; a version 1 document holding a veto is refused.

Version 3 (SPC-203) adds the scenario's probability rule and, beside the rows, the remainder of P the engine weighed
as no adversary action, or null. The remainder row is derived, never stored as a row: the document holds the
operator's rows, the remainder's id, name and P, and a score row for it after theirs, and the reader refuses a
remainder that is not the one the rows leave. Versions 1 and 2, written by 0.28.0 and 0.29.0, are read under the rule
those releases evaluated by, each row weighed by its P over the rows' sum with no remainder, P summing above 1
included, so they replay as they were evaluated then.

Version 4 (SPC-202) adds the scenario's miss rule: element-set error drawn in every sample and a band beside every
computed miss, the score reading its lower edge. Versions 1 to 3, written by 0.28.0 to 0.31.0, are read under the rule
those releases evaluated by, MissRule.POINT, the computed miss scored as it stands and the sampled band over the burn's
spread alone, so they replay as they were evaluated then. Nothing else in the document changed: each element set's
text, epoch and age were stored already, and they are what the error is read from.

Version 5 (SPC-187) adds the scenario's turn rule: a game tree's turns set by the engine from the rows' burn times,
every burn inside its own turn. Versions 1 to 4, written by 0.28.0 to 0.36.0, are read under the equal turns those
releases built every tree over, TurnRule.EQUAL, so a tree they recorded replays exactly as it was built then.

The text is canonical (keys sorted, no spaces, ASCII with every other character escaped, no NaN), so the same inputs
give the same text and its SHA-256 identifies them; a U+0000 is stored escaped, so PostgreSQL's text takes it.

Every dataclass is written field by field from its own declaration, so a field added later cannot be left out
unseen. The reader is strict: it refuses a document whose hash does not match, a key given twice, text not in
canonical form, a schema or a version it does not know, an unknown or a missing field at any depth, a value of the
wrong kind, a scenario the engine itself would refuse, and scores that do not fit the scenario. Each refusal names
where in the document it is. Nothing here imports the web layer.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, cast

import numpy as np

from spectre.astro.monte_carlo import ManoeuvreHypothesis
from spectre.astro.notso import NOTSOType
from spectre.astro.response_burn import BurnAxis
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    HypothesisSource,
    MissRule,
    ProbabilityRule,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    Seen,
    SelectorStrategy,
    ThreatPicture,
    TurnRule,
    with_remainder,
    without_remainder,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.notso_prior import CountedNotice, NotsoPrior
from spectre.domain.provenance import Basis, FigureBasis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Cue, Dimension, Understanding

#: What the document is, and the version of it this code writes (SPC-187: the turn rule).
SCHEMA = "spectre.decision-inputs"
VERSION = 5
#: Every version this code reads: version 1, written by 0.28.0, holds no veto, and reads as nothing vetoed; versions
#: 1 and 2, written by 0.28.0 and 0.29.0, hold no probability rule, and read under the rule they were evaluated by;
#: versions 1 to 3, written by 0.28.0 to 0.31.0, hold no miss rule, and read under the rule they were evaluated by;
#: versions 1 to 4, written by 0.28.0 to 0.36.0, hold no turn rule, and read as the equal turns they were built over.
VERSIONS = (1, 2, 3, 4, 5)
#: The response fields version 2 added (SPC-195), which a version 1 document never holds.
_VETO_FIELDS = frozenset({"vetoed", "veto_reason"})
#: The scenario field version 3 added (SPC-203), and the rule a document without it was evaluated by.
_RULE_FIELD = "probability_rule"
_RULE_BEFORE: dict[str, Any] = {_RULE_FIELD: ProbabilityRule.SHARES}
#: The scenario field version 4 added (SPC-202), and the rule a document without it was evaluated by.
_MISS_FIELD = "miss_rule"
_MISS_BEFORE: dict[str, Any] = {_MISS_FIELD: MissRule.POINT}
#: The scenario field version 5 added (SPC-187), and the rule a document without it was built by.
_TURN_FIELD = "turn_rule"
_TURNS_BEFORE: dict[str, Any] = {_TURN_FIELD: TurnRule.EQUAL}
#: The document's own fields, every one required: version 3 adds the remainder of P (SPC-203).
_TOP = ("schema", "version", "code_version", "rule", "scenario", "scores", "budget_ran_out")
_TOPS: dict[int, tuple[str, ...]] = {
    1: _TOP, 2: _TOP, 3: (*_TOP, "remainder"), 4: (*_TOP, "remainder"), 5: (*_TOP, "remainder"),
}
#: The first version holding the remainder of P (SPC-203).
_REMAINDER_SINCE = 3


class InputsRefusedError(ValueError):
    """Stored inputs this code will not read, with where and why in words; never a partial scenario."""


@dataclass(frozen=True)
class StoredInputs:
    """What a record's stored inputs give back: the scenario, the rule it ran under, the composite scores rows by
    responses, the code version that computed them, and whether its time budget ran out, so that a replay, which runs
    in full, can say a difference may come from what the budget left out."""

    scenario:       Scenario
    rule:           SelectorStrategy
    scores:         tuple[tuple[float, ...], ...]
    code_version:   str
    budget_ran_out: bool


# ── Values ──

#: One field's writer and reader: the value to plain JSON, and plain JSON, read at a place, back to the value.
Codec = tuple[Callable[[Any], Any], Callable[[Any, str], Any]]


def _refuse(where: str, why: str) -> InputsRefusedError:
    return InputsRefusedError(f"Stored inputs refused at {where or 'the top'}: {why}.")


def _plain_out(value: Any) -> Any:
    """A number, text, a truth value or nothing, as JSON holds it; anything else is a field this module must name."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(f"no codec for a {type(value).__name__}")


#: What JSON may hold for a field declared with each plain annotation; a whole number is a number too.
_PLAIN_KINDS: dict[str, tuple[type, ...]] = {"str": (str,), "float": (int, float), "int": (int,), "bool": (bool,)}


def _plain(annotation: str) -> Codec:
    """The codec of a field declared *annotation*: str, float, int or bool, a Literal of text, any of them or None.

    Any other annotation is a field this module must give a codec of its own, and is refused when the module loads.
    """
    optional = annotation.endswith(" | None")
    base = annotation.removesuffix(" | None")
    kinds = _PLAIN_KINDS["str"] if base.startswith("Literal[") else _PLAIN_KINDS.get(base)
    if kinds is None:
        raise TypeError(f"no codec for a field declared {annotation}")

    def read(value: Any, where: str) -> Any:
        if value is None and optional:
            return None
        if not isinstance(value, kinds) or (isinstance(value, bool) and bool not in kinds):
            raise _refuse(where, f"a {type(value).__name__} where {annotation} belongs")
        return value

    return (_plain_out, read)


def _text_in(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise _refuse(where, f"a {type(value).__name__} where text belongs")
    return value


def _number_in(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _refuse(where, f"a {type(value).__name__} where a number belongs")
    return float(value)


def _moment_in(value: Any, where: str) -> datetime:
    text = _text_in(value, where)
    try:
        return datetime.fromisoformat(text)
    except ValueError as error:
        raise _refuse(where, "not an ISO 8601 time") from error


_MOMENT: Codec = (lambda moment: moment.isoformat(), _moment_in)


def _enum(kind: type[Enum]) -> Codec:
    def read(value: Any, where: str) -> Enum:
        try:
            return kind(value)
        except ValueError as error:
            raise _refuse(where, f"{value!r} is no {kind.__name__}") from error

    return (lambda member: member.value, read)


def _optional(inner: Codec) -> Codec:
    write, read = inner
    return (lambda value: None if value is None else write(value),
            lambda value, where: None if value is None else read(value, where))


def _list_in(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _refuse(where, f"a {type(value).__name__} where a list belongs")
    return value


def _many(inner: Codec, kind: Callable[[Any], Any] = tuple) -> Codec:
    write, read = inner
    return (lambda values: [write(v) for v in values],
            lambda value, where: kind(read(v, f"{where}[{i}]") for i, v in enumerate(_list_in(value, where))))


def _pair(inner: Codec) -> Codec:
    write, read = inner

    def read_pair(value: Any, where: str) -> tuple[Any, Any]:
        items = _list_in(value, where)
        # PLR2004: a pair.
        if len(items) != 2:  # noqa: PLR2004
            raise _refuse(where, f"{len(items)} items where a pair belongs")
        return read(items[0], f"{where}[0]"), read(items[1], f"{where}[1]")

    return (lambda pair: [write(pair[0]), write(pair[1])], read_pair)


#: An element set's state as six numbers at full precision; held as an array, as the sampler reads it.
_STATE: Codec = (
    lambda state: [float(x) for x in np.asarray(state, dtype=float)],
    lambda value, where: np.array([_number_in(v, f"{where}[{i}]") for i, v in enumerate(_list_in(value, where))]),
)


# ── Dataclasses, field by field ──

@dataclass(frozen=True)
class _Shape:
    """A dataclass written as an object of its own init fields, each by its codec or as a single value. *omit* names
    fields an earlier version of the document never held, or a field never stored: they are neither written nor
    read, so each takes its value in *fill*, or else its default."""

    kind:    type
    special: Mapping[str, Codec]
    omit:    frozenset[str] = frozenset()
    fill:    Mapping[str, Any] = dataclasses.field(default_factory=dict)
    codecs:  dict[str, Codec] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        declared = {f.name: str(f.type) for f in dataclasses.fields(self.kind) if f.init and f.name not in self.omit}
        unknown = set(self.special) - set(declared)
        if unknown:
            raise TypeError(f"{self.kind.__name__} has no field {', '.join(sorted(unknown))}")
        codecs = {name: self.special.get(name) or _plain(annotation) for name, annotation in declared.items()}
        object.__setattr__(self, "codecs", codecs)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.codecs)

    def write(self, value: Any) -> dict[str, Any]:
        return {name: write(getattr(value, name)) for name, (write, _read) in self.codecs.items()}

    def read(self, value: Any, where: str) -> Any:
        fields = _exactly(value, self.names, where)
        read_in = {name: read(fields[name], f"{where}.{name}") for name, (_write, read) in self.codecs.items()}
        return self.kind(**read_in, **self.fill)

    @property
    def codec(self) -> Codec:
        return (self.write, self.read)


def _exactly(value: Any, names: Sequence[str], where: str) -> dict[str, Any]:
    """*value* as an object holding exactly *names*: an unknown or a missing field is refused, naming it."""
    if not isinstance(value, dict):
        raise _refuse(where, f"a {type(value).__name__} where an object belongs")
    unknown, missing = sorted(set(value) - set(names)), sorted(set(names) - set(value))
    if unknown:
        raise _refuse(where, f"unknown field {', '.join(unknown)}")
    if missing:
        raise _refuse(where, f"missing field {', '.join(missing)}")
    return value


_TRANSFER_BURN = _Shape(TransferBurn, {"at_utc": _MOMENT})
_MANOEUVRE = _Shape(ManoeuvreHypothesis, {"epoch_utc": _MOMENT, "pre_manoeuvre_state_eci_km": _STATE})
_HYPOTHESIS = _Shape(AdversaryHypothesis, {
    "hypothesis": _MANOEUVRE.codec, "source": _enum(HypothesisSource), "then": _many(_TRANSFER_BURN.codec),
})
def _evidence_basis_in(value: Any, where: str) -> Basis:
    """A stored NOTSO suggestion's basis: a judgement (SPC-196) is the operator's, and no version-1 writer ever stored
    one there, so it is refused rather than read."""
    kind = cast("Basis", _enum(Basis)[1](value, where))
    if kind is Basis.JUDGEMENT:
        raise _refuse(where, "a NOTSO suggestion is a lookup, never a judgement")
    return kind


_FIGURE_BASIS = _Shape(FigureBasis, {"kind": (lambda member: member.value, _evidence_basis_in)})
_COUNTED = _Shape(CountedNotice, {"start": _MOMENT, "kind": _enum(NOTSOType)})
_PRIOR = _Shape(NotsoPrior, {
    "action_type": _enum(ActionType), "span_start": _MOMENT, "span_end": _MOMENT,
    "mapped": _many(_enum(NOTSOType)), "basis": _FIGURE_BASIS.codec, "cover": _many(_pair(_MOMENT)),
    "counted": _many(_COUNTED.codec), "until": _optional(_MOMENT),
})
#: A row as stored: the operator's, never the remainder row, which is derived (SPC-203), so its flag is not stored.
_ACTION = _Shape(AdversaryAction, {
    "action_type": _enum(ActionType), "hypothesis": _optional(_HYPOTHESIS.codec), "accepted_prior": _optional(_PRIOR.codec),
}, omit=frozenset({"remainder"}))
_BURN_SPEC = _Shape(ResponseBurnSpec, {"axis": _enum(BurnAxis)})
_RESPONSE_CODECS: dict[str, Codec] = {"action_type": _enum(ActionType), "burn": _optional(_BURN_SPEC.codec)}
_RESPONSE = _Shape(FriendlyResponse, _RESPONSE_CODECS)
#: A response as version 1 holds it, with no veto: read as permitted.
_RESPONSE_V1 = _Shape(FriendlyResponse, _RESPONSE_CODECS, omit=_VETO_FIELDS)
_CUSTODY = _Shape(CustodyStatus, {"state": _enum(Custody)})
_ELSET = _Shape(BoundElset, {"epoch": _optional(_MOMENT), "custody": _optional(_CUSTODY.codec)})
_BINDING = _Shape(ScenarioBinding, {"red": _optional(_ELSET.codec), "blue": _optional(_ELSET.codec)})
_BANDS = _pair(_enum(Band))
_CUE = _Shape(Cue, {"dimensions": _many(_enum(Dimension)), "benign": _BANDS, "hostile": _BANDS})
_PICTURE = _Shape(ThreatPicture, {
    "floor": _enum(Band), "ceiling": _enum(Band), "understanding": _enum(Understanding), "cues": _many(_CUE.codec),
    "decide_at": _optional(_MOMENT), "arrival": _optional(_MOMENT), "assessed_at": _MOMENT,
})
_SCENARIO_CODECS: dict[str, Codec] = {
    "epoch_utc": _MOMENT, "adversary_actions": _many(_ACTION.codec, list), "binding": _optional(_BINDING.codec),
    "threat": _optional(_PICTURE.codec), "observed": _optional(_enum(Seen)),
}
def _write_rule(rule: ProbabilityRule) -> str:
    """The remainder rule, the one version 3 holds. A scenario under the 0.29.0 rule is only ever a replay of a record
    0.28.0 or 0.29.0 wrote, and a replay writes no record, so one is never stored again (SPC-203)."""
    if rule is not ProbabilityRule.REMAINDER:
        raise ValueError(
            "a scenario under the 0.29.0 rule is never stored again: version 3 holds the remainder rule alone, and "
            "only versions 1 and 2, which 0.28.0 and 0.29.0 wrote, read as the 0.29.0 rule"
        )
    return rule.value


def _read_rule(value: Any, where: str) -> ProbabilityRule:
    """The remainder rule, and no other: a version 3 or 4 document under the 0.29.0 rule would replay as evaluated
    before SPC-203, which no such record was."""
    if value != ProbabilityRule.REMAINDER.value:
        raise _refuse(where, f"version 3 holds the remainder rule alone, as version 4 does, not {value!r}; the 0.29.0 "
                             "rule is read only from versions 1 and 2, which 0.28.0 and 0.29.0 wrote")
    return ProbabilityRule.REMAINDER


def _write_miss(rule: MissRule) -> str:
    """The element-set error rule, the one version 4 holds. A scenario under the rule of 0.28.0 to 0.31.0 is only ever
    a replay of a record those releases wrote, and a replay writes no record, so one is never stored again
    (SPC-202)."""
    if rule is not MissRule.ELSET_ERROR:
        raise ValueError(
            "a scenario under the miss rule of 0.28.0 to 0.31.0 is never stored again: version 4 holds the element-set "
            "error rule alone, and only versions 1 to 3, which those releases wrote, read as the rule before it"
        )
    return rule.value


def _read_miss(value: Any, where: str) -> MissRule:
    """The element-set error rule, and no other: a version 4 document under the rule before it would replay as
    evaluated before SPC-202, which no version 4 record was."""
    if value != MissRule.ELSET_ERROR.value:
        raise _refuse(where, f"version 4 holds the element-set error rule alone, not {value!r}; the rule before it is "
                             "read only from versions 1 to 3, which 0.28.0 to 0.31.0 wrote")
    return MissRule.ELSET_ERROR


def _write_turns(rule: TurnRule) -> str:
    """The engine's turns, the one rule version 5 holds. A scenario over equal turns is only ever a replay of a record
    0.28.0 to 0.36.0 wrote, and a replay writes no record, so one is never stored again (SPC-187)."""
    if rule is not TurnRule.BURNS:
        raise ValueError(
            "a scenario over the equal turns of 0.23.0 to 0.36.0 is never stored again: version 5 holds the engine's "
            "turns alone, and only versions 1 to 4, which 0.28.0 to 0.36.0 wrote, read as equal turns"
        )
    return rule.value


def _read_turns(value: Any, where: str) -> TurnRule:
    """The engine's turns, and no other: a version 5 document over equal turns would replay as built before SPC-187,
    which no version 5 record was."""
    if value != TurnRule.BURNS.value:
        raise _refuse(where, f"version 5 holds the engine's turns alone, not {value!r}; equal turns are read only from "
                             "versions 1 to 4, which 0.28.0 to 0.36.0 wrote")
    return TurnRule.BURNS


#: Version 3's probability rule: the remainder rule, written and read, and no other (SPC-203).
_REMAINDER_RULE: Codec = (_write_rule, _read_rule)
#: Version 4's miss rule: the element-set error rule, written and read, and no other (SPC-202).
_ELSET_RULE: Codec = (_write_miss, _read_miss)
#: Version 5's turn rule: the engine's turns, written and read, and no other (SPC-187).
_ENGINE_TURNS: Codec = (_write_turns, _read_turns)
#: The scenario as each version holds it: version 1's responses carry no veto; neither version 1 nor 2 holds the
#: probability rule, so each reads as the rule 0.28.0 and 0.29.0 evaluated by (SPC-203); none of versions 1 to 3
#: holds the miss rule, so each reads as the rule 0.28.0 to 0.31.0 evaluated by (SPC-202); and none of versions 1 to 4
#: holds the turn rule, so each reads as the equal turns 0.28.0 to 0.36.0 built every tree over (SPC-187).
_SCENARIOS: dict[int, _Shape] = {
    1: _Shape(Scenario, {**_SCENARIO_CODECS, "friendly_responses": _many(_RESPONSE_V1.codec, list)},
              omit=frozenset({_RULE_FIELD, _MISS_FIELD, _TURN_FIELD}),
              fill={**_RULE_BEFORE, **_MISS_BEFORE, **_TURNS_BEFORE}),
    2: _Shape(Scenario, {**_SCENARIO_CODECS, "friendly_responses": _many(_RESPONSE.codec, list)},
              omit=frozenset({_RULE_FIELD, _MISS_FIELD, _TURN_FIELD}),
              fill={**_RULE_BEFORE, **_MISS_BEFORE, **_TURNS_BEFORE}),
    3: _Shape(Scenario, {**_SCENARIO_CODECS, "friendly_responses": _many(_RESPONSE.codec, list),
                         _RULE_FIELD: _REMAINDER_RULE}, omit=frozenset({_MISS_FIELD, _TURN_FIELD}),
              fill={**_MISS_BEFORE, **_TURNS_BEFORE}),
    4: _Shape(Scenario, {**_SCENARIO_CODECS, "friendly_responses": _many(_RESPONSE.codec, list),
                         _RULE_FIELD: _REMAINDER_RULE, _MISS_FIELD: _ELSET_RULE}, omit=frozenset({_TURN_FIELD}),
              fill=_TURNS_BEFORE),
    5: _Shape(Scenario, {**_SCENARIO_CODECS, "friendly_responses": _many(_RESPONSE.codec, list),
                         _RULE_FIELD: _REMAINDER_RULE, _MISS_FIELD: _ELSET_RULE, _TURN_FIELD: _ENGINE_TURNS}),
}


def encode_scenario(scenario: Scenario) -> dict[str, Any]:
    """*scenario* as plain JSON values, every field of every part of it, as this version writes it: the operator's
    rows alone, since the remainder row is derived (SPC-203)."""
    return _SCENARIOS[VERSION].write(without_remainder(scenario))


def decode_scenario(document: Any, where: str = "scenario", version: int = VERSION) -> Scenario:
    """The Scenario *document* holds, as *version* of the document holds it, strictly: an unknown, a missing or a
    misshapen field is refused, as is a scenario the engine's own checks refuse."""
    try:
        return _SCENARIOS[version].read(document, where)  # type: ignore[no-any-return]
    except InputsRefusedError:
        raise
    except (ValueError, TypeError) as error:
        raise _refuse(where, f"not a scenario the engine takes ({error})") from error


# ── The document ──

def _remainder_of(scenario: Scenario) -> dict[str, Any] | None:
    """The remainder row *scenario* is evaluated with, as the document holds it beside the rows: its id, name and P;
    None when the rows leave none (SPC-203)."""
    rows = with_remainder(scenario).adversary_actions
    if not rows or not rows[-1].remainder:
        return None
    return {"id": rows[-1].id, "name": rows[-1].name, "probability": rows[-1].probability}


def inputs_document(result: ScenarioResult) -> dict[str, Any]:
    """The canonical inputs of *result*: its scenario, the operator's rows alone, the rule it ran under, its composite
    scores rows by responses, the remainder row's after theirs, the remainder of P, the code version that computed
    them, and whether its time budget ran out."""
    return {
        "schema": SCHEMA, "version": VERSION,
        "code_version": "" if result.provenance is None else result.provenance.code_version,
        "rule": result.robust_strategy.value,
        "scenario": encode_scenario(result.scenario),
        "remainder": _remainder_of(result.scenario),
        "scores": [[cell.composite_score for cell in row] for row in result.outcome_matrix],
        "budget_ran_out": result.budget_ran_out,
    }


def canonical_json(document: Mapping[str, Any]) -> str:
    """*document* as canonical JSON text: keys sorted, no spaces, ASCII only, and no NaN or infinity."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_inputs(result: ScenarioResult) -> tuple[str, str]:
    """The canonical inputs of *result* as stored, with their SHA-256."""
    text = canonical_json(inputs_document(result))
    return text, sha256_of(text)


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse("", f"the key {key!r} is repeated")
        seen[key] = value
    return seen


def _parsed(text: str, sha256: str) -> dict[str, Any]:
    """The document *text* holds, once its hash matches, no key repeats and it is in canonical form."""
    if not sha256 or sha256_of(text) != sha256:
        raise _refuse("", "the text does not match its stored SHA-256, so it is not the text that was stored")
    try:
        document = json.loads(text, object_pairs_hook=_no_repeats)
    except json.JSONDecodeError as error:
        raise _refuse("", "not JSON") from error
    if not isinstance(document, dict):
        raise _refuse("", f"a {type(document).__name__} where the document's object belongs")
    try:
        canonical = canonical_json(document)
    except ValueError as error:   # NaN or infinity, which canonical JSON never holds
        raise _refuse("", "not in canonical form") from error
    if canonical != text:
        raise _refuse("", "not in canonical form")
    return document


def _scores(value: Any, scenario: Scenario) -> tuple[tuple[float, ...], ...]:
    """The composite scores, one row per row evaluated, the remainder row's last where the rows leave one (SPC-203),
    and one number per response; canonical JSON holds no NaN."""
    rows = _list_in(value, "scores")
    wide = len(scenario.friendly_responses)
    evaluated = len(with_remainder(scenario).adversary_actions)
    if len(rows) != evaluated or any(len(_list_in(row, "scores")) != wide for row in rows):
        raise _refuse("scores", "they do not fit the scenario's rows and responses")
    return tuple(
        tuple(_number_in(x, f"scores[{i}][{j}]") for j, x in enumerate(row)) for i, row in enumerate(rows)
    )


def _version(value: Any) -> int:
    """A version this code reads, or refused naming every version it knows."""
    if type(value) is not int or value not in VERSIONS:
        known = ", ".join(str(v) for v in VERSIONS[:-1]) + f" and {VERSIONS[-1]}"
        raise _refuse("version", f"version {value!r} is not one this code reads; it knows versions {known}")
    return value


def read_inputs(text: str, sha256: str) -> StoredInputs:
    """The stored inputs *text*, whose SHA-256 was stored as *sha256*, read strictly; InputsRefusedError otherwise."""
    document = _parsed(text, sha256)
    # The schema, then the version, where the document holds them, before its fields, so a document of another schema
    # or of a version this code does not read is named for it, not for a field this version would hold.
    if "schema" in document and document["schema"] != SCHEMA:
        raise _refuse("schema", f"{document['schema']!r} is not {SCHEMA}")
    version = _version(document["version"]) if "version" in document else VERSION
    document = _exactly(document, _TOPS[version], "")
    rule = _enum(SelectorStrategy)[1](document["rule"], "rule")
    scenario = decode_scenario(document["scenario"], version=version)
    if version >= _REMAINDER_SINCE and document["remainder"] != _remainder_of(scenario):
        raise _refuse("remainder", f"it is not the remainder of P the rows leave, {_remainder_of(scenario)!r}")
    return StoredInputs(
        scenario, rule, _scores(document["scores"], scenario), _text_in(document["code_version"], "code_version"),
        _plain("bool")[1](document["budget_ran_out"], "budget_ran_out"),
    )
