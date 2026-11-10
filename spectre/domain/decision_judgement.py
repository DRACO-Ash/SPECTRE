"""Which of a scenario's inputs are the operator's judgement, and the code version, in words (SPC-196, F-05).

Every figure in a result carries a basis, computed, sampled or lookup, but the values the operator enters carried
none, so an operator could not tell physics from opinion in the inputs to a recommendation (evaluation F-05). Each
input on the panel that enters a score or a pick is listed here with its value and a :class:`FigureBasis`: the
weights, the keep-out distance, the horizon and the number of turns; each response's type, cost, reversibility and
time to execute, and its burn's target, budget and axis; each row's type, P, Conf, and custody gap share where the
rule of thumb reads it; each manoeuvre hypothesis and its sample count; and the turn-1 observation where a tree reads
it.

A value on the panel when the operator evaluates is the operator's judgement, set or kept: the form records no edit
of it, so a value kept where the panel started it is the operator's as much as one typed in, and its note names where
a new panel starts it rather than claim it was typed. Three inputs are not judgements, and say what they rest on
instead: a P the form records as never edited is the panel's default, a lookup (SPC-183); a P or Conf from an applied
NOTSO suggestion is that suggestion's lookup (SPC-130); and a burn detected in the element-set history is what red
did, computed from element sets, as an archetype's typical delta-V is a lookup.

A judgement is an input's basis, not a derived figure's. A figure's mark names the evidence and rules it rests on,
taking the operator's inputs as given: every score and every pick rests on the weights alike, so counting them would
mark every figure a judgement and tell no cell from another, while this list says which inputs they are. Were a
judgement passed to :func:`~spectre.domain.provenance.weakest`, it would pull the figure down to judgement, never
lift it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.domain.decision import (
    DEFAULT_CONFIDENCE,
    DEFAULT_CUSTODY_GAP_FRACTION,
    DEFAULT_HORIZON_H,
    DEFAULT_KEEP_OUT_KM,
    DEFAULT_PROBABILITY,
    DEFAULT_RESPONSE_COST,
    DEFAULT_REVERSIBILITY,
    DEFAULT_TIME_TO_EXECUTE_H,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    HypothesisSource,
    Scenario,
    _keep_out_text,
    _untouched,
)
from spectre.domain.decision_figures import DEFAULT_BUDGET_KM_S
from spectre.domain.manoeuvre_calibration import from_km_s
from spectre.domain.provenance import Basis, FigureBasis

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spectre.domain.provenance import Provenance

#: Heads the list on the results page.
JUDGEMENT_HEAD = (
    "Judgement inputs: the values on the panel when you evaluated, set by you or kept as the panel started them, each "
    "marked with its basis. A judgement is not evidence: a figure's mark names the evidence and rules it rests on, "
    "taking these inputs as given, so no mark rises on one, and the score stays a lookup."
)
#: The code version that computed a result, from its provenance (evaluation F-05). The version is the one SPECTRE
#: reports, which names a release only for a released build.
CODE_VERSION_LINE = (
    "Code version {version}: the version SPECTRE reports for the code that computed this result, from its provenance."
)
CODE_VERSION_UNRECORDED = "Code version not recorded: this result carries no provenance."

_KEPT = "your judgement, set or kept on the panel"
_YOURS = FigureBasis(Basis.JUDGEMENT, _KEPT)
_KEEP_OUT = FigureBasis(
    Basis.JUDGEMENT, f"{_KEPT}; a new panel starts it at {DEFAULT_KEEP_OUT_KM:g} km, Claude's choice and unsourced",
)
_HORIZON = FigureBasis(
    Basis.JUDGEMENT, f"{_KEPT}; a new panel starts it at {DEFAULT_HORIZON_H:g} h, and one opened from a sweep at the "
    "whole hours to red's arrival and one more, up to the longest horizon",
)
_TURNS = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new panel starts it at 1")
_P = FigureBasis(Basis.JUDGEMENT, "your judgement, set on the panel: the form records it as edited (SPC-183)")
_DEFAULT_P = FigureBasis(Basis.LOOKUP, f"the panel's default, {DEFAULT_PROBABILITY:g}, never edited")
_CONF = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at {DEFAULT_CONFIDENCE:g}; it moves no figure")
_GAP = FigureBasis(
    Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at {DEFAULT_CUSTODY_GAP_FRACTION:g}, a rule of thumb",
)
_COST = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at {DEFAULT_RESPONSE_COST:g}")
_REVERSIBILITY = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at {DEFAULT_REVERSIBILITY:g}")
_TIME = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at {DEFAULT_TIME_TO_EXECUTE_H:g} h")
_TARGET = FigureBasis(Basis.JUDGEMENT, "your judgement, set on the panel: with no target, no burn is sized")
_BUDGET = FigureBasis(
    Basis.JUDGEMENT, "your judgement: the budget set on the panel or, left blank, the default "
    f"{from_km_s(DEFAULT_BUDGET_KM_S):g} m/s (DEFAULT_BUDGET_KM_S in docs/lookup-register.md), kept by leaving it "
    "blank",
)
_AXIS = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; a new row starts it at cheapest")
_OBSERVED = FigureBasis(Basis.JUDGEMENT, "your statement of what turn 1 showed")
_ENTERED = FigureBasis(
    Basis.JUDGEMENT, "your judgement: the delta-V and direction entered on the panel, what red might do, not what it "
    "did",
)
_ARCHETYPE = FigureBasis(
    Basis.JUDGEMENT, "your judgement: the archetype chosen on the panel, what red might do, not what it did",
)
_ARCHETYPE_DV = FigureBasis(
    Basis.LOOKUP, "the archetype's typical delta-V, from MANOEUVRE_ARCHETYPES in docs/lookup-register.md",
)
_DETECTED = FigureBasis(
    Basis.COMPUTED, "detected in the object's element-set history: what red did, read from element sets, not a "
    "judgement",
)
_SPREAD = FigureBasis(Basis.JUDGEMENT, "your judgement, entered on the panel in place of the archetype's spread")
_SAMPLES = FigureBasis(Basis.JUDGEMENT, f"{_KEPT}; with fewer than 50 the row is not sampled")

#: What a response's cost moves, by its action type, as the lookup model reads it (compute_outcome_metrics).
_COST_READS: dict[ActionType, str] = {
    ActionType.MANOEUVRE: "cost raises its closest approach and sets its delta-V where those are lookups.",
    ActionType.POSTURE_CHANGE: "cost raises its closest approach where that is a lookup.",
    ActionType.SENSOR_RETASK: "its cost moves no figure.",
    ActionType.NO_ACTION: "its cost moves no figure.",
}
#: The responses against which the rule of thumb holds custody of a manoeuvring row, so its gap share sets nothing.
_HOLDS_CUSTODY = frozenset({ActionType.MANOEUVRE, ActionType.SENSOR_RETASK})

_WEIGHTS: tuple[tuple[str, str], ...] = (
    ("w_custody", "custody"), ("w_closest_approach", "closest approach"), ("w_dv_cost", "our delta-V"),
    ("w_time_to_exec", "time to execute"), ("w_reversibility", "reversibility"),
)


@dataclass(frozen=True)
class Judged:
    """One input as the results show it: its name, its value in the operator's units, and what it rests on."""

    name: str
    shown: str
    basis: FigureBasis

    @property
    def text(self) -> str:
        """"cost 0.3 (judgement)": the name, the value and the basis in words."""
        return f"{' '.join(part for part in (self.name, self.shown) if part)} ({self.basis.kind.value})"


@dataclass(frozen=True)
class JudgementLine:
    """One line of the list: whose inputs, each input, and what reads them."""

    subject: str
    inputs: tuple[Judged, ...]
    reads: str

    @property
    def sentence(self) -> str:
        return f"{self.subject}: {', '.join(i.text for i in self.inputs)}. {self.reads}"


@dataclass(frozen=True)
class RowInputs:
    """The bases of an adversary row's type, P, Conf and custody gap share, as its matrix row shows them."""

    action_type: FigureBasis
    probability: FigureBasis
    confidence: FigureBasis
    custody_gap_fraction: FigureBasis


@dataclass(frozen=True)
class ResponseInputs:
    """The bases of a response's type, cost, reversibility and time to execute, as the headline shows them."""

    action_type: FigureBasis
    cost: FigureBasis
    reversibility: FigureBasis
    time_to_execute: FigureBasis


def _type_text(kind: ActionType) -> str:
    return kind.value.replace("_", " ")


def row_inputs(action: AdversaryAction) -> RowInputs:
    """A row's type, P and Conf are the operator's judgement, unless the form records P as never edited, when it is
    the panel's default, or an applied NOTSO suggestion supplied them, when they are its lookup."""
    prior = action.accepted_prior
    if prior is not None:
        confidence = _CONF if prior.confidence is None else prior.basis
        return RowInputs(_YOURS, prior.basis, confidence, _GAP)
    return RowInputs(_YOURS, _DEFAULT_P if _untouched(action) else _P, _CONF, _GAP)


def response_inputs(_response: FriendlyResponse) -> ResponseInputs:
    """A response's type, cost, reversibility and time to execute: always the operator's judgement, set or kept."""
    return ResponseInputs(_YOURS, _COST, _REVERSIBILITY, _TIME)


def _weight_basis(name: str) -> FigureBasis:
    start = getattr(Scenario, name)
    return FigureBasis(
        Basis.JUDGEMENT, f"{_KEPT}; a new panel starts it at {start:g}, and the weights are scaled to sum to one; the "
        "panel's starting weights are not yet cited (SPC-151)",
    )


def _scenario_lines(scenario: Scenario) -> list[JudgementLine]:
    weights = tuple(Judged(label, f"{getattr(scenario, name):.4g}", _weight_basis(name)) for name, label in _WEIGHTS)
    turns = ("One turn: the outcome matrix alone, no game tree." if scenario.turns == 1 else
             "Above one turn, a game tree is built where both sides are bound and current, and its pick heads the "
             "results.")
    return [
        JudgementLine("Weights", weights, "They weight every score, so every pick."),
        JudgementLine("Keep-out distance", (Judged("", f"{_keep_out_text(scenario.keep_out_km)} km", _KEEP_OUT),),
                      "It sets where closest approach scores its full penalty."),
        JudgementLine("Horizon", (Judged("", f"{scenario.horizon_hours:g} h", _HORIZON),),
                      "It sets the span searched, and every score's custody gap and time to execute are read "
                      "against it."),
        JudgementLine("Turns", (Judged("", f"{scenario.turns}", _TURNS),), turns),
    ]


def _response_line(response: FriendlyResponse) -> JudgementLine:
    inputs = [
        Judged("type", _type_text(response.action_type), _YOURS),
        Judged("cost", f"{response.cost:g}", _COST),
        Judged("reversibility", f"{response.reversibility:g}", _REVERSIBILITY),
        Judged("time to execute", f"{response.time_to_execute_hours:g} h", _TIME),
    ]
    reads = ("Its type selects how the lookup model reads it; reversibility and time to execute enter each of its "
             f"scores; {_COST_READS[response.action_type]}")
    if response.burn is not None:
        inputs += [
            Judged("target separation", f"{response.burn.target_km:g} km", _TARGET),
            Judged("delta-V budget", f"{from_km_s(response.burn.budget_km_s):g} m/s", _BUDGET),
            Judged("burn axis", response.burn.axis.value, _AXIS),
        ]
        reads += " The target, budget and axis size its burn where both sides are bound."
    return JudgementLine(f"{response.name} ({response.id})", tuple(inputs), reads)


def _source_inputs(carried: AdversaryHypothesis) -> list[Judged]:
    """What the hypothesis rests on, by where it came from: entered, an archetype chosen, or a burn detected."""
    if carried.source is HypothesisSource.DETECTED:
        return [Judged("detected burn", "", _DETECTED)]
    if carried.source is HypothesisSource.ARCHETYPE:
        archetype = MANOEUVRE_ARCHETYPES[str(carried.archetype_key)]
        delta_v = from_km_s(carried.hypothesis.delta_v_magnitude_km_s)
        return [Judged("archetype", archetype.name, _ARCHETYPE), Judged("its delta-V", f"{delta_v:g} m/s", _ARCHETYPE_DV)]
    return [Judged("manoeuvre hypothesis", "entered", _ENTERED)]


def _hypothesis_line(subject: str, carried: AdversaryHypothesis, sampled: bool) -> JudgementLine:
    inputs = _source_inputs(carried)
    if carried.spread_entered:
        spread = from_km_s(carried.hypothesis.delta_v_magnitude_1sigma_km_s)
        inputs.append(Judged("delta-V spread", f"{spread:g} m/s", _SPREAD))
    inputs.append(Judged("samples", f"{carried.hypothesis.n_samples}", _SAMPLES))
    what = ("What red did, read from its element-set history, not a judgement." if carried.source is
            HypothesisSource.DETECTED else "What red might do, not what it did.")
    used = (" Its row's closest approach is sampled from it." if sampled else
            " Nothing was sampled from it on this evaluation: the row's cells say what each figure rests on.")
    return JudgementLine(subject, tuple(inputs), what + used)


def _row_lines(action: AdversaryAction, gap_read: bool, sampled: bool) -> list[JudgementLine]:
    bases = row_inputs(action)
    inputs = [Judged("type", _type_text(action.action_type), bases.action_type),
              Judged("P", f"{action.probability:g}", bases.probability),
              Judged("Conf", f"{action.confidence:g}", bases.confidence)]
    reads = ("Its type selects its lookup closest approach and custody rule; P weights it under expected value; Conf "
             "moves no figure.")
    if gap_read:
        inputs.append(Judged("custody gap share", f"{action.custody_gap_fraction:g}", bases.custody_gap_fraction))
        reads += (" The gap share sets its custody gap by rule of thumb against a response that neither manoeuvres "
                  "nor retasks a sensor.")
    subject = f"{action.name} ({action.id})"
    lines = [JudgementLine(subject, tuple(inputs), reads)]
    if action.hypothesis is not None:
        lines.append(_hypothesis_line(subject, action.hypothesis, sampled))
    return lines


def judgement_lines(
    scenario: Scenario, row_custody: Sequence[str | None], row_sampled: Sequence[bool] = (),
) -> tuple[JudgementLine, ...]:
    """Every input on the panel that enters a score or a pick, a line per subject.

    *row_custody* is the result's sentence per row when its custody is not the rule of thumb, and *row_sampled*
    whether any of the row's closest approaches was sampled. A row's custody gap share is listed only where it sets a
    figure: on a manoeuvre row whose custody is the rule of thumb, with a response that neither manoeuvres nor
    retasks a sensor, against which the rule loses custody.
    """
    lines = _scenario_lines(scenario)
    lines += [_response_line(response) for response in scenario.friendly_responses]
    loses_custody = any(r.action_type not in _HOLDS_CUSTODY for r in scenario.friendly_responses)
    for i, action in enumerate(scenario.adversary_actions):
        read = i < len(row_custody) and row_custody[i] is not None
        sampled = i < len(row_sampled) and row_sampled[i]
        gap_read = action.action_type is ActionType.MANOEUVRE and not read and loses_custody
        lines += _row_lines(action, gap_read, sampled)
    if scenario.turns > 1 and scenario.observed is not None:
        lines.append(JudgementLine("Turn 1", (Judged("shows", scenario.observed.value, _OBSERVED),),
                                   "Under expected value, the update after turn 1 reads it."))
    return tuple(lines)


def code_version_line(provenance: Provenance | None) -> str:
    """The code version that computed a result, in words, or that none is recorded."""
    if provenance is None:
        return CODE_VERSION_UNRECORDED
    return CODE_VERSION_LINE.format(version=provenance.code_version)
