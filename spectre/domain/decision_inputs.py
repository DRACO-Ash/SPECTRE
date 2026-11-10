"""Decision Engine: an evaluation's canonical inputs, written and read strictly (SPC-193, evaluation F-02).

Provenance hashed every input and stored none, so once the sign-in ended a recommendation could not be reproduced.
A decision record now keeps one JSON document holding:

● the whole Scenario: its rows, responses, weights, horizon, turns, keep-out distance and observation; every
  hypothesis with its dispersions and seed; each accepted NOTSO prior; the threat picture; and the binding, with each
  bound element set's text, epoch, age, limit, data mode and custody;
● the rule the evaluation ran under, the result's composite score matrix and the code version that computed it;
● whether its time budget ran out, which a replay, run in full, cannot repeat, so it says so.

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
from typing import Any

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
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    Seen,
    SelectorStrategy,
    ThreatPicture,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.notso_prior import CountedNotice, NotsoPrior
from spectre.domain.provenance import Basis, FigureBasis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Cue, Dimension, Understanding

#: What the document is, and the one version of it this code reads and writes.
SCHEMA = "spectre.decision-inputs"
VERSION = 1
#: The document's own fields, every one required.
_TOP = ("schema", "version", "code_version", "rule", "scenario", "scores", "budget_ran_out")


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
        if len(items) != 2:  # noqa: PLR2004 - a pair
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
    """A dataclass written as an object of its own init fields, each by its codec or as a single value."""

    kind:    type
    special: Mapping[str, Codec]
    codecs:  dict[str, Codec] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        declared = {f.name: str(f.type) for f in dataclasses.fields(self.kind) if f.init}
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
        return self.kind(**{name: read(fields[name], f"{where}.{name}") for name, (_write, read) in self.codecs.items()})

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
_FIGURE_BASIS = _Shape(FigureBasis, {"kind": _enum(Basis)})
_COUNTED = _Shape(CountedNotice, {"start": _MOMENT, "kind": _enum(NOTSOType)})
_PRIOR = _Shape(NotsoPrior, {
    "action_type": _enum(ActionType), "span_start": _MOMENT, "span_end": _MOMENT,
    "mapped": _many(_enum(NOTSOType)), "basis": _FIGURE_BASIS.codec, "cover": _many(_pair(_MOMENT)),
    "counted": _many(_COUNTED.codec), "until": _optional(_MOMENT),
})
_ACTION = _Shape(AdversaryAction, {
    "action_type": _enum(ActionType), "hypothesis": _optional(_HYPOTHESIS.codec), "accepted_prior": _optional(_PRIOR.codec),
})
_BURN_SPEC = _Shape(ResponseBurnSpec, {"axis": _enum(BurnAxis)})
_RESPONSE = _Shape(FriendlyResponse, {"action_type": _enum(ActionType), "burn": _optional(_BURN_SPEC.codec)})
_CUSTODY = _Shape(CustodyStatus, {"state": _enum(Custody)})
_ELSET = _Shape(BoundElset, {"epoch": _optional(_MOMENT), "custody": _optional(_CUSTODY.codec)})
_BINDING = _Shape(ScenarioBinding, {"red": _optional(_ELSET.codec), "blue": _optional(_ELSET.codec)})
_BANDS = _pair(_enum(Band))
_CUE = _Shape(Cue, {"dimensions": _many(_enum(Dimension)), "benign": _BANDS, "hostile": _BANDS})
_PICTURE = _Shape(ThreatPicture, {
    "floor": _enum(Band), "ceiling": _enum(Band), "understanding": _enum(Understanding), "cues": _many(_CUE.codec),
    "decide_at": _optional(_MOMENT), "arrival": _optional(_MOMENT), "assessed_at": _MOMENT,
})
_SCENARIO = _Shape(Scenario, {
    "epoch_utc": _MOMENT, "adversary_actions": _many(_ACTION.codec, list),
    "friendly_responses": _many(_RESPONSE.codec, list), "binding": _optional(_BINDING.codec),
    "threat": _optional(_PICTURE.codec), "observed": _optional(_enum(Seen)),
})


def encode_scenario(scenario: Scenario) -> dict[str, Any]:
    """*scenario* as plain JSON values, every field of every part of it."""
    return _SCENARIO.write(scenario)


def decode_scenario(document: Any, where: str = "scenario") -> Scenario:
    """The Scenario *document* holds, strictly: an unknown, a missing or a misshapen field is refused, as is a
    scenario the engine's own checks refuse."""
    try:
        return _SCENARIO.read(document, where)  # type: ignore[no-any-return]
    except InputsRefusedError:
        raise
    except (ValueError, TypeError) as error:
        raise _refuse(where, f"not a scenario the engine takes ({error})") from error


# ── The document ──

def inputs_document(result: ScenarioResult) -> dict[str, Any]:
    """The canonical inputs of *result*: its scenario, the rule it ran under, its composite scores rows by responses,
    the code version that computed them, and whether its time budget ran out."""
    return {
        "schema": SCHEMA, "version": VERSION,
        "code_version": "" if result.provenance is None else result.provenance.code_version,
        "rule": result.robust_strategy.value,
        "scenario": encode_scenario(result.scenario),
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
    """The composite scores, one row per adversary row and one number per response; canonical JSON holds no NaN."""
    rows = _list_in(value, "scores")
    wide = len(scenario.friendly_responses)
    if len(rows) != len(scenario.adversary_actions) or any(len(_list_in(row, "scores")) != wide for row in rows):
        raise _refuse("scores", "they do not fit the scenario's rows and responses")
    return tuple(
        tuple(_number_in(x, f"scores[{i}][{j}]") for j, x in enumerate(row)) for i, row in enumerate(rows)
    )


def read_inputs(text: str, sha256: str) -> StoredInputs:
    """The stored inputs *text*, whose SHA-256 was stored as *sha256*, read strictly; InputsRefusedError otherwise."""
    document = _exactly(_parsed(text, sha256), _TOP, "")
    if document["schema"] != SCHEMA:
        raise _refuse("schema", f"{document['schema']!r} is not {SCHEMA}")
    if type(document["version"]) is not int or document["version"] != VERSION:
        raise _refuse("version", f"version {document['version']!r} is not one this code reads; it knows version {VERSION}")
    rule = _enum(SelectorStrategy)[1](document["rule"], "rule")
    scenario = decode_scenario(document["scenario"])
    return StoredInputs(
        scenario, rule, _scores(document["scores"], scenario), _text_in(document["code_version"], "code_version"),
        _plain("bool")[1](document["budget_ran_out"], "budget_ran_out"),
    )
