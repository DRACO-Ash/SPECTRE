"""Decision Engine: scenario evaluation, from lookups and a sampled closest approach.

Evaluates a grid of adversary actions × friendly responses with a lookup model
and a weighted composite scoring function. Custody, closest approach, time to
approach and delta-V are rules of thumb and constants per action type, scaled
by the operator's inputs, and they are uncalibrated against any observed
outcome. A selector (minimax by default) picks the friendly response with the
least worst-case cost.

Every figure in a cell states its own basis (lookup, sampled or computed),
and the score's basis is derived from the figures it uses, never stronger
than lookup while its weights are rules of thumb (SPC-101).

An earlier "TLE refinement" took one instant's separation, could only lower
the estimate, hid every error behind a bare except, and never ran because the
route passed no red element set; it was removed (audit F-111).

A scenario may be bound to a held red track and blue asset (SPC-100). The
binding names the real objects the scenario is about and carries their element
sets, their epochs and their ages at evaluation. It is shown with the result
and goes into its provenance, and on its own changes no figure.

An adversary action may carry a manoeuvre hypothesis (SPC-111): how the
adversary might move, taken from an archetype in the Monte Carlo table, a
delta-V and RIC direction the operator entered, or a manoeuvre detected in the
object's element-set history. It travels with its source, the archetype's name
and the direction's frame and basis, so a reader can tell an assumed direction
from a measured one (audit F-104), and it is checked when it is built. It goes
into the result's provenance and the scenario's recorded value, and on its own
changes no figure.

When a row's action carries a hypothesis and the scenario is bound on both
sides, that row's closest approach is sampled (SPC-112): plan_sampling runs
the Monte Carlo engine's separation series against the blue asset, and every
cell of the row scores on P5 of the sampled misses, the smallest-miss tail,
with its time to closest approach the earliest at or below P5. Every other
figure, and every other row, is still a lookup. A row that cannot be sampled
honestly (too few samples, an out-of-date orbit, a hypothesis built from
another element set, a failed or unconverged series, or a scenario over the
cost cap) is refused with a sentence in each of its cells and keeps its lookups.

Typical use::

    scenario = Scenario(
        name="GEO intercept threat",
        epoch_utc=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        adversary_actions=[...],
        friendly_responses=[...],
        horizon_hours=72.0,
    )
    result = evaluate_scenario(scenario)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, cast

import numpy as np

from spectre.astro.monte_carlo import (
    _MIN_CONVERGENCE_SAMPLES,
    CONVERGENCE_TOLERANCE_KM,
    MANOEUVRE_ARCHETYPES,
    BlueTrack,
    ManoeuvreHypothesis,
    ManoeuvreType,
    SeparationSeries,
    SeparationWindow,
    _ric_split,
    elset_state,
    hypothesis_from_tle_record,
    run_separation_series,
    separation_integration_s,
)
from spectre.domain.custody import age_text
from spectre.domain.manoeuvre_calibration import from_km_s, to_km_s
from spectre.domain.provenance import (
    Basis,
    FigureBasis,
    InputRef,
    Provenance,
    provenance,
    tle_input,
    value_input,
    weakest,
)

if TYPE_CHECKING:
    from spectre.astro.pattern_of_life import Manoeuvre, TLERecord

logger = logging.getLogger(__name__)

# ── Enumerations ──────────────────────────────────────────────────────────────

class ActionType(Enum):
    MANOEUVRE        = "manoeuvre"
    SENSOR_RETASK    = "sensor_retask"
    POSTURE_CHANGE   = "posture_change"
    NO_ACTION        = "no_action"


class SelectorStrategy(Enum):
    MINIMAX           = "minimax"           # minimise worst-case cost
    EXPECTED_VALUE    = "expected_value"    # minimise expected cost (uses probability)
    # Minimise the BEST-case cost: the optimistic rule, not a robust one. It
    # was labelled MAXIMIN, the name of the cautious rule, so an operator
    # asking for caution got the riskiest response (audit F-S05-01).
    MINIMIN           = "minimin"


#: What every Phase 1 outcome rests on, shown to the operator with the result.
MODELLED_BASIS = (
    "Outcomes are Phase 1 lookup constants and weights, not propagated orbits: "
    "closest approach is a fixed figure per action type scaled by response cost, "
    "time to approach is a fixed fraction of the horizon, and custody follows a "
    "rule of thumb. Use it to compare trade-offs, not as an operational answer."
)


# ── Figure bases ──────────────────────────────────────────────────────────────

#: The figures composite_score is built from, read off its formula: norm_custody uses custody_maintained and
#: custody_gap_hours, norm_ca closest_approach_km, norm_dv delta_v_cost_km_s. time_to_closest_hours is not used.
_SCORE_INPUTS: tuple[str, ...] = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "delta_v_cost_km_s")
#: The weights and the normalisations (50,000 km; 0.1 km/s, i.e. 100 m/s) are rules of thumb, so the score
#: is never stronger than lookup, whatever its figures are. Citing the weights (SPC-151) does not change this.
_SCORING_RULE_KIND: Basis = Basis.LOOKUP


@dataclass(frozen=True)
class OutcomeBases:
    """What each figure of one cell rests on, one :class:`FigureBasis` per OutcomeMetrics figure."""

    custody_maintained:    FigureBasis
    custody_gap_hours:     FigureBasis
    closest_approach_km:   FigureBasis
    time_to_closest_hours: FigureBasis
    delta_v_cost_km_s:     FigureBasis
    composite_score:       FigureBasis

    def __post_init__(self) -> None:
        ceiling = weakest(_SCORING_RULE_KIND, *(getattr(self, name).kind for name in _SCORE_INPUTS))
        if self.composite_score.kind != weakest(self.composite_score.kind, ceiling):
            raise ValueError(
                f"composite_score cannot claim {self.composite_score.kind.value}: "
                f"its scoring rule and figures support at most {ceiling.value}"
            )

    def items(self) -> tuple[tuple[str, FigureBasis], ...]:
        """Each figure's name and basis, in field order."""
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


_SCORE_NOTE = (
    "weighted sum of custody, closest approach and our delta-V with the response's time to execute and "
    "reversibility; weights as set on the panel, scaled to sum to one, defaults not yet cited (SPC-151); closest approach normalised "
    "to 50,000 km and delta-V to 0.1 km/s (100 m/s); never stronger than lookup"
)


def outcome_bases(
    *,
    custody_maintained: FigureBasis,
    custody_gap_hours: FigureBasis,
    closest_approach_km: FigureBasis,
    time_to_closest_hours: FigureBasis,
    delta_v_cost_km_s: FigureBasis,
) -> OutcomeBases:
    """The bases of one cell, with the score's derived from the figures it uses.

    The only builder for OutcomeBases: a later release sets one figure's
    kind (SPC-120: closest approach computed) and the score follows.
    """
    inputs = {
        "custody_maintained": custody_maintained,
        "custody_gap_hours": custody_gap_hours,
        "closest_approach_km": closest_approach_km,
        "delta_v_cost_km_s": delta_v_cost_km_s,
    }
    score_kind = weakest(_SCORING_RULE_KIND, *(inputs[name].kind for name in _SCORE_INPUTS))
    return OutcomeBases(
        time_to_closest_hours=time_to_closest_hours,
        composite_score=FigureBasis(score_kind, _SCORE_NOTE),
        **inputs,
    )


#: Each figure's name as the operator reads it.
FIGURE_LABELS: dict[str, str] = {
    "custody_maintained": "custody",
    "custody_gap_hours": "custody gap",
    "closest_approach_km": "closest approach",
    "time_to_closest_hours": "time to closest approach",
    "delta_v_cost_km_s": "our delta-V",
    "composite_score": "score",
}

#: Phase 1: every figure is a lookup, and each note matches compute_outcome_metrics as written.
LOOKUP_BASES: OutcomeBases = outcome_bases(
    custody_maintained=FigureBasis(
        Basis.LOOKUP,
        "rule of thumb: lost when the adversary manoeuvres and the response neither manoeuvres nor retasks "
        "a sensor; not the held, degraded or lost custody on the sweep",
    ),
    custody_gap_hours=FigureBasis(
        Basis.LOOKUP,
        "when custody is lost, the horizon x adversary confidence; against a sensor retask, half its time "
        "to execute; detection is not modelled",
    ),
    closest_approach_km=FigureBasis(
        Basis.LOOKUP,
        "a fixed 200, 3,000, 5,000 or 10,000 km per adversary action type, raised by response cost for a "
        "manoeuvre or posture change; no orbit propagated",
    ),
    time_to_closest_hours=FigureBasis(Basis.LOOKUP, "0.4 of the horizon"),
    delta_v_cost_km_s=FigureBasis(
        Basis.LOOKUP, "response cost x 0.05 km/s (0 to 50 m/s) for a manoeuvre response, else 0",
    ),
)

#: The result's basis once its figures rest on more than one kind; the lines list them.
MIXED_BASIS = (
    "Figures rest on mixed bases, listed below and marked in each cell. "
    "The ranking is still a weighted heuristic."
)

_ALL_LOOKUP_LINE = "Every figure in every cell is a lookup."


def _cell_bases(cell: object) -> OutcomeBases:
    """A cell's bases. An unrecorded basis reads as a lookup, never as computed."""
    bases = getattr(cell, "figure_bases", None)
    return bases if isinstance(bases, OutcomeBases) else LOOKUP_BASES


def _is_modelled(bases: OutcomeBases) -> bool:
    return any(fb.kind is not Basis.COMPUTED for _, fb in bases.items())


def _all_lookup(bases: OutcomeBases) -> bool:
    return all(fb.kind is Basis.LOOKUP for _, fb in bases.items())


def _figure_line(label: str, counts: Counter[Basis], total: int) -> str:
    """One banner line, kinds weakest first: "Closest approach: lookup in 1 of 2 cells, computed in 1." """
    present = [(kind, counts[kind]) for kind in Basis if counts[kind]]   # Basis is declared weakest first
    head = label[:1].upper() + label[1:]
    if len(present) == 1:
        return f"{head}: {present[0][0].value} in every cell."
    (first, n_first), *rest = present
    parts = [f"{first.value} in {n_first} of {total} cells", *(f"{kind.value} in {n}" for kind, n in rest)]
    return f"{head}: {', '.join(parts)}."


# ── Data classes ──────────────────────────────────────────────────────────────

def _require_fraction(owner: str, field_name: str, value: float) -> None:
    """Refuse a value outside [0, 1], NaN or infinite included (audit F-112)."""
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        raise ValueError(f"{owner}.{field_name} must be in [0, 1]; got {value!r}")


# ── Manoeuvre hypothesis (SPC-111) ────────────────────────────────────────────

#: Shown with every hypothesis once the panel carries one (SPC-114).
HYPOTHESIS_NOTE: str = (
    "A manoeuvre hypothesis records how the adversary might move and where that came from. It changes no "
    "figure unless both sides are bound; then the closest approach of its row and its time are sampled from it, "
    "and every other figure is still a lookup."
)


class HypothesisSource(StrEnum):
    """Where an adversary action's manoeuvre hypothesis came from."""

    ARCHETYPE = "archetype"     # a row of MANOEUVRE_ARCHETYPES
    ENTERED = "entered"         # a delta-V and direction the operator gave
    DETECTED = "detected"       # a manoeuvre detected in the object's element-set history


#: The frames a hypothesis's direction may be read in. ManoeuvreHypothesis holds radial, in-track and
#: cross-track parts, so RIC is the only one until a later release adds another.
_FRAMES = frozenset({"RIC"})
#: Radial, in-track and cross-track.
_RIC_AXES = 3
#: Below this norm, or above any finite one, generate_samples cannot read the direction and quietly points the
#: burn in-track, so parts outside that range are stored at unit length instead.
_MIN_DIRECTION_NORM = 1e-15
#: The spreads a sampler draws from, each with how a refusal names it.
_DISPERSIONS: tuple[tuple[str, str], ...] = (
    ("delta_v_magnitude_1sigma_km_s", "delta-V spread"),
    ("delta_v_pointing_1sigma_deg", "pointing spread"),
    ("epoch_1sigma_seconds", "timing spread"),
    ("bstar_1sigma", "B* spread"),
)
_ARCHETYPE_DIRECTION = "assumed in-track: an archetype names no direction"
_ENTERED_DIRECTION = "entered by the operator"
_SOURCE_LEADS: dict[HypothesisSource, str] = {
    HypothesisSource.ARCHETYPE: "Archetype {archetype}",
    HypothesisSource.ENTERED: "Entered by the operator",
    HypothesisSource.DETECTED: "Detected manoeuvre",
}


class PreManoeuvreState(NamedTuple):
    """Where and when the adversary is just before the hypothesised burn."""

    epoch_utc:    datetime
    state_eci_km: Sequence[float]     # [x, y, z, vx, vy, vz]: km, and km per second


def _known_archetype(key: str) -> ManoeuvreType:
    archetype = MANOEUVRE_ARCHETYPES.get(key)
    if archetype is None:
        raise ValueError(
            f"{key!r} is not a known manoeuvre archetype; choose one of {', '.join(MANOEUVRE_ARCHETYPES)}."
        )
    return archetype


def _unit_ric(direction: Sequence[float]) -> tuple[float, float, float]:
    """*direction* scaled to unit length, refused when it has no length to scale.

    The parts are divided by the largest first, so a direction of any finite
    size normalises without its squares underflowing or overflowing.
    """
    parts = tuple(float(c) for c in direction)
    if len(parts) != _RIC_AXES or not all(math.isfinite(c) for c in parts):
        raise ValueError(
            f"A direction is three finite parts, radial, in-track and cross-track; got {tuple(direction)!r}."
        )
    peak = max(abs(c) for c in parts)
    if peak == 0.0:
        raise ValueError("A direction of zero cannot be normalised, and no direction is assumed in its place.")
    scaled = tuple(c / peak for c in parts)
    norm = math.hypot(*scaled)
    return (scaled[0] / norm, scaled[1] / norm, scaled[2] / norm)


def _parts(hypothesis: ManoeuvreHypothesis) -> tuple[float, float, float]:
    return (hypothesis.delta_v_radial, hypothesis.delta_v_in_track, hypothesis.delta_v_cross_track)


def _sampler_reads(parts: Sequence[float]) -> bool:
    """Whether generate_samples can read *parts* as a direction rather than quietly assume in-track."""
    norm = float(np.linalg.norm(np.asarray(parts, dtype=float)))
    return math.isfinite(norm) and norm >= _MIN_DIRECTION_NORM


def _pointed(hypothesis: ManoeuvreHypothesis, unit: tuple[float, float, float]) -> ManoeuvreHypothesis:
    """*hypothesis* along *unit*, scaled by its delta-V where the sampler can read that, else at unit length.

    The parts only point, so a zero or tiny burn keeps its direction this way.
    """
    scaled = tuple(hypothesis.delta_v_magnitude_km_s * c for c in unit)
    parts = scaled if _sampler_reads(scaled) else unit
    return dataclasses.replace(
        hypothesis, delta_v_radial=parts[0], delta_v_in_track=parts[1], delta_v_cross_track=parts[2],
    )


def _nominal(dv_km_s: float, unit: tuple[float, float, float], at: PreManoeuvreState, basis: str) -> ManoeuvreHypothesis:
    """The burn along *unit*."""
    return _pointed(
        ManoeuvreHypothesis(
            epoch_utc=at.epoch_utc,
            delta_v_magnitude_km_s=dv_km_s,
            delta_v_radial=unit[0],
            delta_v_in_track=unit[1],
            delta_v_cross_track=unit[2],
            pre_manoeuvre_state_eci_km=np.array(at.state_eci_km, dtype=float),
            direction_basis=basis,
        ),
        unit,
    )


def _dispersed(hypothesis: ManoeuvreHypothesis, archetype: ManoeuvreType | None, n_samples: int) -> ManoeuvreHypothesis:
    """*hypothesis* with *archetype*'s dispersions and name; the ManoeuvreHypothesis defaults when there is none."""
    if archetype is None:
        return dataclasses.replace(hypothesis, n_samples=n_samples)
    return dataclasses.replace(
        hypothesis,
        delta_v_magnitude_1sigma_km_s=hypothesis.delta_v_magnitude_km_s * archetype.delta_v_1sigma_fraction,
        delta_v_pointing_1sigma_deg=archetype.pointing_1sigma_deg,
        epoch_1sigma_seconds=archetype.timing_1sigma_seconds,
        archetype=archetype.name,
        n_samples=n_samples,
    )


def _require_origin(carried: AdversaryHypothesis) -> None:
    """The source, frame, direction basis and archetype say how the hypothesis was made, and agree."""
    if not isinstance(carried.source, HypothesisSource):
        raise ValueError(f"A hypothesis's source is archetype, entered or detected; got {carried.source!r}.")
    if carried.frame not in _FRAMES:
        raise ValueError(f"A hypothesis's direction is read in the RIC frame; got frame {carried.frame!r}.")
    if not carried.hypothesis.direction_basis.strip():
        raise ValueError("A hypothesis states its direction basis, so a reader can tell an assumed direction.")
    named = carried.hypothesis.archetype
    if carried.archetype_key is None:
        if carried.source is not HypothesisSource.ENTERED:
            raise ValueError(f"A {carried.source.value} hypothesis names its archetype.")
        if named:
            raise ValueError(f"A hypothesis with no archetype key names no archetype; it names {named}.")
        return
    expected = _known_archetype(carried.archetype_key).name
    if named != expected:
        raise ValueError(f"Archetype {carried.archetype_key!r} names {expected}, not {named or 'nothing'}.")


def _require_burn(hypothesis: ManoeuvreHypothesis) -> None:
    """The burn is finite and not negative, points somewhere, starts from a real state and is sampled at least once."""
    dv = hypothesis.delta_v_magnitude_km_s
    if not (math.isfinite(dv) and dv >= 0.0):
        raise ValueError(f"A hypothesis's delta-V must be finite and not negative; got {from_km_s(dv)!r} m/s.")
    _unit_ric(_parts(hypothesis))
    _require_dispersions(hypothesis)
    state = np.asarray(hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
    if state.shape != (6,) or not bool(np.all(np.isfinite(state))):
        raise ValueError("The pre-manoeuvre state is six finite numbers: position in km, then velocity.")
    if hypothesis.n_samples < 1:
        raise ValueError(f"A hypothesis's sample count must be at least 1; got {hypothesis.n_samples!r}.")


def _require_dispersions(hypothesis: ManoeuvreHypothesis) -> None:
    """Every spread the sampler draws from is finite and not negative; zero means none."""
    for name, label in _DISPERSIONS:
        value = getattr(hypothesis, name)
        if not (math.isfinite(value) and value >= 0.0):
            shown = f"{from_km_s(value)!r} m/s" if name.endswith("_km_s") else repr(value)
            raise ValueError(f"A hypothesis's {label} must be finite and not negative; got {shown}.")


class _SealedHypothesis(ManoeuvreHypothesis):
    """A ManoeuvreHypothesis no field of which can be written or deleted once it is built.

    A frozen dataclass cannot inherit from a plain one, so the seal is set at
    the end of construction. ``dataclasses.replace`` still works, and gives
    another sealed copy.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise dataclasses.FrozenInstanceError(f"cannot assign to field {name!r}: a carried hypothesis is sealed")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        raise dataclasses.FrozenInstanceError(f"cannot delete field {name!r}: a carried hypothesis is sealed")


def _sealed_copy(hypothesis: ManoeuvreHypothesis) -> _SealedHypothesis:
    """A sealed copy, so the checks made at construction keep holding whatever the caller does later.

    Its direction is put where the sampler can read it, and its state is held
    in memory that cannot be made writeable again.
    """
    if not _sampler_reads(_parts(hypothesis)):
        hypothesis = _pointed(hypothesis, _unit_ric(_parts(hypothesis)))
    state = np.frombuffer(np.asarray(hypothesis.pre_manoeuvre_state_eci_km, dtype=float).tobytes(), dtype=float)
    values = {f.name: getattr(hypothesis, f.name) for f in dataclasses.fields(hypothesis)}
    return _SealedHypothesis(**{**values, "pre_manoeuvre_state_eci_km": state})


@dataclass(frozen=True, eq=False)
class AdversaryHypothesis:
    """A manoeuvre hypothesis for one adversary action, with where it came from.

    Build one with :meth:`from_archetype`, :meth:`from_entered` or
    :meth:`from_detection`. It carries the source, the archetype's key and name
    and the direction's frame and basis, so a reader can always tell how it
    was made (audit F-104). It is checked here, whoever builds it, and the
    hypothesis is held as a sealed copy, so no later change, to the caller's
    object or to the one carried, can undo the check.
    """

    hypothesis:    ManoeuvreHypothesis
    source:        HypothesisSource
    archetype_key: str | None = None
    frame:         str = "RIC"

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis, ManoeuvreHypothesis):
            raise TypeError(f"AdversaryHypothesis holds a ManoeuvreHypothesis; got {type(self.hypothesis).__name__}")
        _require_origin(self)
        _require_burn(self.hypothesis)
        object.__setattr__(self, "hypothesis", _sealed_copy(self.hypothesis))

    @classmethod
    def from_archetype(
        cls, archetype: str, at: PreManoeuvreState, *, direction_ric: Sequence[float] | None = None,
        n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """An archetype's typical burn and dispersions, in-track unless a direction is entered."""
        row = _known_archetype(archetype)
        unit, basis = (0.0, 1.0, 0.0), _ARCHETYPE_DIRECTION
        if direction_ric is not None:
            unit, basis = _unit_ric(direction_ric), _ENTERED_DIRECTION
        nominal = _nominal(row.typical_delta_v_km_s, unit, at, basis)
        return cls(_dispersed(nominal, row, n_samples), HypothesisSource.ARCHETYPE, archetype_key=archetype)

    @classmethod
    def from_entered(
        cls, delta_v_m_s: float, direction_ric: Sequence[float], at: PreManoeuvreState, *,
        archetype: str | None = None, n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """A delta-V the operator entered, in m/s, along a RIC direction, with an archetype's dispersions if named."""
        row = None if archetype is None else _known_archetype(archetype)
        nominal = _nominal(to_km_s(delta_v_m_s), _unit_ric(direction_ric), at, _ENTERED_DIRECTION)
        return cls(_dispersed(nominal, row, n_samples), HypothesisSource.ENTERED, archetype_key=archetype)

    @classmethod
    def from_detection(
        cls, tle_record: TLERecord, manoeuvre: Manoeuvre, *, archetype: str, n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """A detected manoeuvre's burn and direction, with *archetype*'s dispersions.

        The archetype is checked first: hypothesis_from_tle_record would read
        an unknown one as an orbit raise and say nothing. A detection of no or
        almost no delta-V keeps the detection's direction at unit length,
        where the split would have scaled it to nothing.
        """
        _known_archetype(archetype)
        built = hypothesis_from_tle_record(tle_record, manoeuvre, n_samples=n_samples, archetype_override=archetype)
        if not _sampler_reads(_parts(built)):
            unit, _basis = _ric_split(getattr(manoeuvre, "breakdown", None))
            built = _pointed(built, _unit_ric(unit.tolist()))
        return cls(built, HypothesisSource.DETECTED, archetype_key=archetype)

    @property
    def archetype(self) -> str:
        """The archetype's name, or empty when the dispersions are the defaults."""
        return self.hypothesis.archetype

    @property
    def direction_basis(self) -> str:
        return self.hypothesis.direction_basis

    @property
    def delta_v_m_s(self) -> float:
        return from_km_s(self.hypothesis.delta_v_magnitude_km_s)

    @property
    def direction_ric(self) -> tuple[float, float, float]:
        h = self.hypothesis
        return _unit_ric((h.delta_v_radial, h.delta_v_in_track, h.delta_v_cross_track))

    @property
    def sentence(self) -> str:
        """How the hypothesis was made, in one sentence."""
        lead = _SOURCE_LEADS[self.source].format(archetype=self.archetype)
        spread = f"dispersions from the {self.archetype} archetype" if self.archetype else "default dispersions, no archetype"
        return f"{lead}: {self.delta_v_m_s:.1f} m/s; direction ({self.frame}) {self.direction_basis}; {spread}."

    @property
    def note(self) -> str:
        """HYPOTHESIS_NOTE, here for a template whose only context is the result."""
        return HYPOTHESIS_NOTE

    def recorded(self) -> dict[str, object]:
        """The hypothesis as plain values, for provenance: every figure at full precision."""
        inner = dataclasses.asdict(self.hypothesis)
        inner["epoch_utc"] = self.hypothesis.epoch_utc.isoformat()
        inner["pre_manoeuvre_state_eci_km"] = [float(x) for x in self.hypothesis.pre_manoeuvre_state_eci_km]
        return {"source": self.source.value, "archetype_key": self.archetype_key, "frame": self.frame, "hypothesis": inner}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AdversaryHypothesis):
            return NotImplemented
        return self.recorded() == other.recorded()

    def __hash__(self) -> int:
        return hash(json.dumps(self.recorded(), sort_keys=True))


@dataclass
class AdversaryAction:
    """A single adversary COA to evaluate."""

    id:          str
    name:        str
    action_type: ActionType
    probability: float            # [0, 1] — operator assessment
    confidence:  float            # [0, 1] — intelligence confidence
    description: str = ""
    # How the adversary might move, and where that came from (SPC-111). Carried
    # and put in provenance; in a scenario bound on both sides, plan_sampling
    # samples this row's closest approach from it (SPC-112).
    hypothesis:  AdversaryHypothesis | None = None

    def __post_init__(self) -> None:
        _require_fraction("AdversaryAction", "probability", self.probability)
        _require_fraction("AdversaryAction", "confidence", self.confidence)
        if self.hypothesis is not None and not isinstance(self.hypothesis, AdversaryHypothesis):
            raise TypeError(
                "AdversaryAction.hypothesis takes an AdversaryHypothesis, which says where the hypothesis came "
                f"from; got {type(self.hypothesis).__name__}"
            )


@dataclass
class FriendlyResponse:
    """A single friendly COA to evaluate against each adversary action."""

    id:                   str
    name:                 str
    action_type:          ActionType
    cost:                 float    # Normalised [0, 1] — propellant, ops tempo, etc.
    reversibility:        float    # [0, 1] — 1 = fully reversible
    time_to_execute_hours: float   # Execution latency
    description:          str = ""

    def __post_init__(self) -> None:
        _require_fraction("FriendlyResponse", "cost", self.cost)
        _require_fraction("FriendlyResponse", "reversibility", self.reversibility)
        if not (math.isfinite(self.time_to_execute_hours) and self.time_to_execute_hours >= 0.0):
            raise ValueError(
                f"FriendlyResponse.time_to_execute_hours must be finite and >= 0; "
                f"got {self.time_to_execute_hours!r}"
            )


@dataclass
class OutcomeMetrics:
    """Deterministic outcome metrics for one (adversary_action, friendly_response) pair."""

    custody_maintained:   bool
    custody_gap_hours:    float     # 0 if custody maintained
    closest_approach_km:  float
    time_to_closest_hours: float
    delta_v_cost_km_s:    float    # Friendly ΔV expended
    composite_score:      float    # Higher = worse for friendly
    # What each figure above rests on, carried on the data so no consumer can
    # present a lookup as computed. The default is the weakest basis, so a
    # path that forgets to set it under-claims rather than over-claims.
    figure_bases:         OutcomeBases = LOOKUP_BASES
    # A sampled closest approach (SPC-112): P5, P50 and P95 of the misses in
    # km, at full precision, and their standard deviation. Set exactly when the
    # closest approach's basis is sampled; closest_approach_km is then P5.
    ca_percentiles:       dict[int, float] | None = None
    ca_std_km:            float | None = None
    # How many sampled misses the band is taken over, set with the band.
    ca_samples:           int | None = None
    # Why a row that carries a hypothesis was not sampled, ending "lookups".
    ca_refusal:           str | None = None
    # What P5 does not say about a sampled cell: the closest sample, and any
    # that were still closing when the window ended.
    ca_caveat:            str | None = None

    def __post_init__(self) -> None:
        sampled = _cell_bases(self).closest_approach_km.kind is Basis.SAMPLED
        band = (self.ca_percentiles, self.ca_std_km, self.ca_samples)
        if not all((part is not None) == sampled for part in band):
            raise ValueError(
                "ca_percentiles, ca_std_km and ca_samples are set exactly when the closest approach's basis is sampled"
            )
        if self.ca_percentiles is not None:
            _require_band(self.ca_percentiles, cast("float", self.ca_std_km), self.closest_approach_km)
            if self.ca_refusal is not None:
                raise ValueError("a cell is sampled or refused, not both")
        elif self.ca_caveat is not None:
            raise ValueError("a caveat on the sampled closest approach needs a sampled band")

    @property
    def ca_band(self) -> str | None:
        """The sampled band in one sentence, for the cell; None when the closest approach is not sampled."""
        if self.ca_percentiles is None:
            return None
        p = self.ca_percentiles
        return f"Sampled: P5 {p[5]:.1f} km to P95 {p[95]:.1f} km, median {p[50]:.1f} km, {self.ca_samples} samples."

    @property
    def modelled(self) -> bool:
        """True while any figure is not computed: always in Phase 1, since the score is a lookup."""
        return _is_modelled(self.figure_bases)

    @property
    def basis(self) -> str:
        if _all_lookup(self.figure_bases):
            return MODELLED_BASIS
        return "; ".join(f"{FIGURE_LABELS[name]}: {fb.kind.value}, {fb.note}" for name, fb in self.figure_bases.items())

    def __str__(self) -> str:
        cust = "✓" if self.custody_maintained else "✗"
        return (
            f"Custody:{cust}  CA:{self.closest_approach_km:.1f}km  "
            f"ΔV:{self.delta_v_cost_km_s*1000:.1f}m/s  "
            f"Score:{self.composite_score:.3f}"
        )


_PERCENTILE_KEYS = (5, 50, 95)


def _require_band(percentiles: dict[int, float], std_km: float, closest_approach_km: float) -> None:
    """P5, P50 and P95 are finite, not negative and in order, and the closest approach shown is P5."""
    if tuple(sorted(percentiles)) != _PERCENTILE_KEYS:
        raise ValueError(f"ca_percentiles holds P5, P50 and P95, keyed 5, 50 and 95; got keys {sorted(percentiles)}")
    values = [percentiles[k] for k in _PERCENTILE_KEYS] + [std_km]
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"the sampled band and its spread must be finite; got {percentiles} and {std_km!r}")
    if not all(v >= 0.0 for v in values):
        raise ValueError(f"the sampled band and its spread must not be negative; got {percentiles} and {std_km!r}")
    p5, p50, p95 = (percentiles[k] for k in _PERCENTILE_KEYS)
    if not p5 <= p50 <= p95:
        raise ValueError(f"the sampled band must hold P5 <= P50 <= P95; got {percentiles}")
    if closest_approach_km != round(p5, 1):
        raise ValueError(f"a sampled cell scores and shows P5, {round(p5, 1)} km; got {closest_approach_km!r} km")


# ── Binding to real objects (SPC-100) ─────────────────────────────────────────

#: Shown with every binding, on the panel and with the result.
BINDING_NOTE: str = (
    "Binding records which real objects this scenario is about. It changes no figure unless an adversary "
    "action carries a hypothesis and both sides are bound; then the closest approach of that row and its time are "
    "sampled from these orbits, and every other figure is still a lookup."
)

_SIDES = frozenset({"red", "blue"})


class Freshness(StrEnum):
    """How a bound element set's age at evaluation stands against its regime's limit."""

    CURRENT = "current"
    OUT_OF_DATE = "out of date"
    UNKNOWN = "unknown"


def _require_side(elset: BoundElset) -> None:
    if elset.side not in _SIDES:
        raise ValueError(f"BoundElset.side must be red or blue; got {elset.side!r}")


def _require_age_facts(elset: BoundElset) -> None:
    """The epoch, age and limit are all known or all unknown, and a known age and limit make sense."""
    facts = (elset.epoch, elset.age_hours, elset.limit_hours)
    if all(f is None for f in facts):
        return
    if elset.epoch is None or elset.age_hours is None or elset.limit_hours is None:
        raise ValueError("an element set's epoch, age and limit are read together")
    if not (math.isfinite(elset.age_hours) and elset.age_hours >= 0.0):
        raise ValueError(f"BoundElset.age_hours must be finite and >= 0; got {elset.age_hours!r}")
    if not (math.isfinite(elset.limit_hours) and elset.limit_hours > 0.0):
        raise ValueError(f"BoundElset.limit_hours must be finite and > 0; got {elset.limit_hours!r}")


_FRESHNESS_SENTENCES: dict[Freshness, str] = {
    Freshness.CURRENT: "Orbit current: {age} old at evaluation, limit {limit}.",
    Freshness.OUT_OF_DATE: (
        "Orbit out of date: {age} old at evaluation against a {limit} limit, "
        "so a burn since its epoch would not be seen."
    ),
    Freshness.UNKNOWN: "Its epoch cannot be read, so its age is unknown; read it as out of date.",
}


@dataclass(frozen=True)
class BoundElset:
    """One held object a scenario is bound to, with its element set's age at evaluation.

    The age and limit are worked out where the element set is read and passed
    in as plain values, so the domain stays free of the web layer. All three
    of epoch, age and limit are None when the epoch cannot be read.
    """

    side:        Literal["red", "blue"]
    name:        str
    stk_name:    str
    satno:       int | None
    tle:         str
    data_mode:   str
    epoch:       datetime | None
    age_hours:   float | None
    limit_hours: float | None
    training:    bool = False

    def __post_init__(self) -> None:
        _require_side(self)
        _require_age_facts(self)

    @property
    def freshness(self) -> Freshness:
        """The sweep's staleness rule (ElsetAge.stale): out of date only when the age is past the limit."""
        if self.age_hours is None or self.limit_hours is None:
            return Freshness.UNKNOWN
        return Freshness.OUT_OF_DATE if self.age_hours > self.limit_hours else Freshness.CURRENT

    @property
    def age_label(self) -> str | None:
        return None if self.age_hours is None else age_text(self.age_hours)

    @property
    def limit_label(self) -> str | None:
        return None if self.limit_hours is None else f"{self.limit_hours:.0f} h"

    @property
    def sentence(self) -> str:
        """The orbit's age in a sentence: it says orbit, never custody."""
        return _FRESHNESS_SENTENCES[self.freshness].format(age=self.age_label, limit=self.limit_label)


@dataclass(frozen=True)
class ScenarioBinding:
    """The red track and blue asset a scenario is about; at least one of them."""

    red:  BoundElset | None = None
    blue: BoundElset | None = None

    def __post_init__(self) -> None:
        if self.red is None and self.blue is None:
            raise ValueError("a binding names at least one object; pass binding=None for an unbound scenario")
        if self.red is not None and self.red.side != "red":
            raise ValueError("ScenarioBinding.red must hold a red element set")
        if self.blue is not None and self.blue.side != "blue":
            raise ValueError("ScenarioBinding.blue must hold a blue element set")

    @property
    def bound(self) -> tuple[BoundElset, ...]:
        """The bound element sets, red first."""
        return tuple(b for b in (self.red, self.blue) if b is not None)

    @property
    def note(self) -> str:
        """BINDING_NOTE, here for the results template, whose only context is the result."""
        return BINDING_NOTE


@dataclass
class Scenario:
    """A what-if scenario: N adversary actions × M friendly responses."""

    name:               str
    epoch_utc:          datetime
    adversary_actions:  list[AdversaryAction]
    friendly_responses: list[FriendlyResponse]
    horizon_hours:      float = 72.0

    # Scoring weights (sum should equal 1)
    w_custody:          float = 0.35    # Penalty for losing custody
    w_closest_approach: float = 0.25    # Reward for maximising CA distance
    w_dv_cost:          float = 0.20    # Penalty for ΔV expenditure
    w_time_to_exec:     float = 0.10    # Penalty for slow response
    w_reversibility:    float = 0.10    # Reward for reversible actions

    # The real objects this scenario is about (SPC-100). Carried, shown and put
    # in provenance; read only by plan_sampling, for a row with a hypothesis.
    binding:            ScenarioBinding | None = None

    def __post_init__(self) -> None:
        # A zero horizon divided by zero in the score (audit F-112).
        if not (math.isfinite(self.horizon_hours) and self.horizon_hours > 0.0):
            raise ValueError(f"Scenario.horizon_hours must be finite and > 0; got {self.horizon_hours!r}")
        for name in ("w_custody", "w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
            _require_fraction("Scenario", name, getattr(self, name))


@dataclass
class ScenarioResult:
    """Evaluated scenario with ranked responses and a robust recommendation."""

    scenario:               Scenario
    # outcome_matrix[i][j] = OutcomeMetrics for (adversary i, friendly j)
    outcome_matrix:         list[list[OutcomeMetrics]]
    # ranked_responses[i][j] = (friendly_response, score) sorted best→worst for adversary i
    ranked_per_adversary:   list[list[tuple[FriendlyResponse, float]]]
    # The robust best response (minimax by default)
    robust_best_response:   FriendlyResponse
    robust_strategy:        SelectorStrategy
    computation_time_s:     float
    # The code, calibration and scenario behind this result (audit F-121).
    provenance:             Provenance | None = None
    # Per adversary row: why a hypothesis it carries was not sampled, else None (SPC-112).
    row_notes:              tuple[str | None, ...] = ()

    # The flag and basis are worked out from the cells, so the page says what
    # the outcomes rest on (audit F-S05-02, and the "modelled estimate" banner
    # agreed in July 2026) and cannot claim more than the cells do.

    def _bases(self) -> list[OutcomeBases]:
        return [_cell_bases(cell) for row in self.outcome_matrix for cell in row]

    @property
    def modelled(self) -> bool:
        bases = self._bases()
        return not bases or any(_is_modelled(b) for b in bases)

    @property
    def basis(self) -> str:
        """MODELLED_BASIS while every figure is a lookup, else MIXED_BASIS; never the lines repeated."""
        return MODELLED_BASIS if all(_all_lookup(b) for b in self._bases()) else MIXED_BASIS

    @property
    def custody_rule_of_thumb(self) -> bool:
        """Whether any cell's custody is still the rule of thumb, so the page says so only then."""
        return any(b.custody_maintained.kind is Basis.LOOKUP for b in self._bases())

    @property
    def basis_lines(self) -> tuple[str, ...]:
        """One line per figure saying which kinds it rests on and in how many cells."""
        bases = self._bases()
        if all(_all_lookup(b) for b in bases):
            return (_ALL_LOOKUP_LINE,)
        return tuple(
            _figure_line(label, Counter(getattr(b, name).kind for b in bases), len(bases))
            for name, label in FIGURE_LABELS.items()
        )

    def _bands(self) -> list[dict[int, float]]:
        cells = (cell for row in self.outcome_matrix for cell in row)
        return [band for cell in cells if (band := getattr(cell, "ca_percentiles", None)) is not None]

    @property
    def n_sampled_cells(self) -> int:
        """How many cells score on a sampled closest approach."""
        return len(self._bands())

    @property
    def sampled_caveat(self) -> str | None:
        """What a sampled closest approach does not say, with how far its spread can move a score; None unsampled."""
        bands = self._bands()
        if not bands:
            return None
        w = self.scenario.w_closest_approach
        delta = max(w * (_norm_ca(band[5]) - _norm_ca(band[95])) for band in bands)
        return _RESULT_CAVEAT.format(delta=delta)


# ── Scoring ────────────────────────────────────────────────────────────────────

class _Figures(NamedTuple):
    """The figures a score is built from, unrounded: custody, its gap, closest approach and our delta-V."""

    custody_maintained:  bool
    custody_gap_hours:   float
    closest_approach_km: float
    delta_v_km_s:        float


#: The lookup closest approach per adversary action type, km; any other type is 3,000 km.
_BASE_CA_KM: dict[ActionType, float] = {
    ActionType.NO_ACTION: 5000.0,        # no approach threat
    ActionType.MANOEUVRE: 200.0,         # potential approach
    ActionType.SENSOR_RETASK: 10000.0,   # not a physical threat
}
_OTHER_CA_KM = 3000.0
#: The score's closest approach normalisation, km: no threat at or beyond it.
_CA_NORMALISATION_KM = 50_000.0


def compute_outcome_metrics(
    adversary: AdversaryAction,
    friendly: FriendlyResponse,
    scenario: Scenario,
) -> OutcomeMetrics:
    """Outcome metrics for one (adversary, friendly) pair, from the lookup model.

    Rules as implemented (Phase 1, uncalibrated)
    --------------------------------------------
    - custody: lost when the adversary manoeuvres and the response is
      NO_ACTION or POSTURE_CHANGE; a MANOEUVRE or SENSOR_RETASK response keeps it
    - custody_gap_hours: when lost, horizon * adversary confidence, a property
      of the adversary's action alone; against a SENSOR_RETASK response to a
      manoeuvre, half the response's time to execute. Detection capability is
      not modelled. Friendly reversibility counts only in its own term: it
      used to scale this gap too, so a fully reversible NO_ACTION lost custody
      at no cost and won the minimax ranking (audit F-035)
    - closest_approach_km: a constant per adversary action type, raised by
      response cost for a MANOEUVRE (x(1 + 5 cost)) or POSTURE_CHANGE
      (x(1 + 2 cost)) response
    - time_to_closest_hours: 0.4 of the horizon
    - delta_v_cost_km_s: friendly.cost * 0.05 for a MANOEUVRE response, else 0
    - composite_score: weighted sum of the normalised terms (higher = worse)

    It never reads the scenario's binding or the action's hypothesis: a
    sampled row is filled by evaluate_scenario from plan_sampling (SPC-112).
    """
    figures = _lookup_figures(adversary, friendly, scenario)
    return OutcomeMetrics(
        custody_maintained=figures.custody_maintained,
        custody_gap_hours=round(figures.custody_gap_hours, 2),
        closest_approach_km=round(figures.closest_approach_km, 1),
        time_to_closest_hours=round(scenario.horizon_hours * 0.4, 2),   # Phase 1: simplified
        delta_v_cost_km_s=round(figures.delta_v_km_s, 5),
        composite_score=round(_score(scenario, friendly, figures), 6),
        figure_bases=LOOKUP_BASES,
    )


def _lookup_figures(adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario) -> _Figures:
    """The lookup model's custody, gap, closest approach and delta-V, unrounded."""
    # ── Custody ──────────────────────────────────────────────────────────────
    adversary_is_manoeuvre = adversary.action_type == ActionType.MANOEUVRE
    friendly_is_active     = friendly.action_type in (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK)

    custody_maintained = True
    custody_gap_hours  = 0.0

    if adversary_is_manoeuvre and not friendly_is_active:
        custody_maintained = False
        # Gap proportional to adversary confidence and horizon, and nothing of
        # ours: how reversible our response is does not shorten their gap.
        custody_gap_hours = scenario.horizon_hours * adversary.confidence
    elif adversary_is_manoeuvre and friendly.action_type == ActionType.SENSOR_RETASK:
        # Sensor retask reduces gap but doesn't eliminate manoeuvre risk
        custody_maintained = True
        custody_gap_hours  = friendly.time_to_execute_hours * 0.5

    # ── Closest approach ─────────────────────────────────────────────────────
    # Phase 1: analytic estimate based on action type pairing
    base_ca_km = _BASE_CA_KM.get(adversary.action_type, _OTHER_CA_KM)

    # Friendly response modifies CA distance
    if friendly.action_type == ActionType.MANOEUVRE:
        ca_km = base_ca_km * (1.0 + friendly.cost * 5.0)  # increase separation
    elif friendly.action_type == ActionType.POSTURE_CHANGE:
        ca_km = base_ca_km * (1.0 + friendly.cost * 2.0)
    else:
        ca_km = base_ca_km

    # ── ΔV cost ───────────────────────────────────────────────────────────────
    dv_km_s = friendly.cost * 0.05 if friendly.action_type == ActionType.MANOEUVRE else 0.0   # 0–50 m/s range

    return _Figures(custody_maintained, custody_gap_hours, ca_km, dv_km_s)


def _norm_ca(ca_km: float) -> float:
    """Closest approach as a score term: 1 at 0 km (co-location), 0 at 50,000 km or more (no threat)."""
    return 1.0 - min(ca_km / _CA_NORMALISATION_KM, 1.0)


def _score(scenario: Scenario, friendly: FriendlyResponse, figures: _Figures) -> float:
    """The composite score (higher = worse), unrounded.

    Each component is normalised to [0, 1] with domain assumptions:
    custody loss 0 when maintained, 1 for a full-horizon gap; closest approach
    inverted, 0 km to 50,000 km; delta-V 0 to 0.1 km/s (100 m/s); time to
    execute 0 to the full horizon; reversibility inverted, a reward.
    """
    norm_custody  = 0.0 if figures.custody_maintained else min(figures.custody_gap_hours / scenario.horizon_hours, 1.0)
    norm_ca       = _norm_ca(figures.closest_approach_km)   # high CA = low score (good)
    norm_dv       = min(figures.delta_v_km_s / 0.1, 1.0)
    norm_time     = min(friendly.time_to_execute_hours / scenario.horizon_hours, 1.0)
    norm_rev      = 1.0 - friendly.reversibility          # reward reversibility → lower score

    return (
        scenario.w_custody          * norm_custody
        + scenario.w_closest_approach * norm_ca
        + scenario.w_dv_cost          * norm_dv
        + scenario.w_time_to_exec     * norm_time
        + scenario.w_reversibility    * norm_rev
    )


# ── Sampled closest approach (SPC-112) ─────────────────────────────────────────

#: A sampler: one hypothesis's separation series against the blue track over a window (SPC-110).
Sampler = Callable[[ManoeuvreHypothesis, BlueTrack, SeparationWindow], SeparationSeries]

#: The most sample-hours one evaluation may run while the operator waits. Until SPC-113 moves it off,
#: POST /decision/evaluate is an async route that calls evaluate_scenario directly, so a sampled evaluation
#: blocks the event loop: every session in the process waits with the operator, not only their request. A row
#: costs the larger of its samples times the horizon and the hours its series integrates
#: (separation_integration_s, which counts any burn before the window), plus SET_UP_S_PER_SAMPLE for each
#: sample; the rows that would run are summed before any of them runs. See _cost for the measurements.
MAX_SAMPLE_HOURS: float = 600.0
#: What one sample costs whatever its window, in seconds of sample time: its solve_ivp set-up and its
#: closest-approach search. Fitted as wall = a x sample-hours + b x samples over six evaluations from 58
#: samples over 10 h to 20,000 over 0.028 h: b / a = 0.146 h, rounded up to 9 minutes. Without it the cap did
#: not bound wall time: 20,000 samples over 0.028 h counted 560 sample-hours and ran for 49 s.
SET_UP_S_PER_SAMPLE: float = 540.0
#: How far, km, the hypothesis's pre-burn position may sit from the bound red track at its burn time. J2000
#: against TEME differs by about 46 km at LEO radius and 275 km at GEO in 2026, so a frame mix is caught.
START_TOLERANCE_KM: float = 10.0
_SECONDS_PER_HOUR = 3600.0
_TENTH_HOUR_S = 360.0

_LOOKUPS = " This cell's figures are lookups."
_OVER_CAP = (
    "Not sampled: this scenario needs at least {total:,} sample-hours (samples times the hours each is "
    "propagated, counting any burn before the window, plus {set_up:g} minutes of set-up for each sample, across "
    "{rows}), above the {cap:,.0f} this page can run while you wait. "
)
_SHORTEN = "At these sample counts the longest horizon that fits is {h:.1f} h."
_NO_HORIZON = (
    "No horizon of 0.1 h or more fits at these sample counts: take fewer samples, at least {least}, or start the "
    "scenario nearer the burn."
)
_TOO_FEW = "Not sampled: {n} samples are fewer than the {least} the convergence check needs."
_STALE = (
    "Not sampled: the {side} orbit is out of date or its age is unknown, so a miss sampled from it would not be "
    "earned."
)
_AFTER_BURN = (
    "Not sampled: the red element set dates from {epoch:%Y-%m-%d %H:%M} UTC, after the burn at "
    "{burn:%Y-%m-%d %H:%M} UTC, so it may already include the burn, and sampling would apply it twice."
)
_NO_STATE = "Not sampled: the {side} element set cannot be propagated to {when:%Y-%m-%d %H:%M} UTC."
_START_MISMATCH = (
    "Not sampled: the hypothesis starts {d:.1f} km from the bound red track at its burn time, more than "
    "{tol:g} km, so it was built from another element set, time or frame."
)
_FAILED = "Not sampled: {k} of {n} samples failed to propagate, and a P5 without them could hide the closest."
_UNCONVERGED = (
    "Not sampled: P5, P50 and P95 are known only to within {hw:.1f} km, wider than the {tol:g} km convergence "
    "check. Take more samples, with a shorter horizon if that goes over the {cap:,.0f} sample-hour cap."
)
_SAMPLED_CA_NOTE = (
    "P5 of {n} sampled misses, known to within {hw:.2f} km (95 % bootstrap): 1 in 20 samples came closer. "
    "Each sample is the hypothesis's burn drawn from its delta-V, pointing, timing and drag spreads, propagated "
    "with the blue asset over the {horizon:g} h horizon from the scenario epoch by RK45 with J2 and exponential "
    "drag; the element sets' own errors are not sampled, and our response is not applied to the blue orbit"
)
_SAMPLED_TIME_NOTE = (
    "earliest time of closest approach among the samples at or below P5, of {n} samples over the {horizon:g} h "
    "horizon from the scenario epoch; RK45 with J2 and exponential drag"
)
_CELL_CAVEAT = "1 in 20 samples came closer than P5; the closest of {n} was {closest:.1f} km."
_EDGE_CAVEAT = (
    " In {k} of {n} samples the objects were still closing when the window ended, so the closest approach may "
    "come after it."
)
_RESULT_CAVEAT = (
    "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers only the "
    "hypothesis: its delta-V, pointing, timing and drag. Element-set errors, and the hypothesis being wrong, are "
    "not in it. Our response is not applied to the blue orbit yet, so every response in a sampled row has the "
    "same closest approach. The score normalises closest approach to 50,000 km, so the sampled spread moves it "
    "by at most {delta:.4f} here."
)
#: A row whose action carries a hypothesis in a scenario not bound on both sides.
UNSAMPLED_ROW_NOTE = (
    "Hypothesis carried, not sampled: bind a red track and a blue asset to sample its closest approach."
)


class RowSampling(NamedTuple):
    """One eligible row's separation series, or why it was not sampled; never both."""

    series:  SeparationSeries | None
    refusal: str | None


class _Row(NamedTuple):
    """What an eligible row is checked and sampled from."""

    hypothesis: ManoeuvreHypothesis
    red:        BoundElset
    blue:       BoundElset
    blue_track: BlueTrack | None   # blue's SGP4 state at the window start
    red_track:  BlueTrack | None   # red's SGP4 state at the hypothesis's burn
    window:     SeparationWindow


def _refusal(sentence: str) -> str:
    return sentence + _LOOKUPS


def _too_few(row: _Row) -> str | None:
    n = row.hypothesis.n_samples
    return _TOO_FEW.format(n=n, least=_MIN_CONVERGENCE_SAMPLES) if n < _MIN_CONVERGENCE_SAMPLES else None


def _stale(row: _Row) -> str | None:
    for elset in (row.red, row.blue):
        if elset.freshness is not Freshness.CURRENT:
            return _STALE.format(side=elset.side)
    return None


def _after_burn(row: _Row) -> str | None:
    """An element set fitted after the burn may already include it, and the series would then apply it twice.

    The start check below cannot see this: an impulsive burn changes velocity, not position, so an element set
    that includes the burn sits where the pre-burn track does at the burn time.
    """
    epoch, burn = row.red.epoch, row.hypothesis.epoch_utc
    return _AFTER_BURN.format(epoch=epoch, burn=burn) if epoch is not None and epoch > burn else None


def _no_state(row: _Row) -> str | None:
    if row.blue_track is None:
        return _NO_STATE.format(side="blue", when=row.window.start_utc)
    if row.red_track is None:
        return _NO_STATE.format(side="red", when=row.hypothesis.epoch_utc)
    return None


def _start_mismatch(row: _Row) -> str | None:
    """Position only: within the 10 km tolerance, velocity may differ by about 11 m/s from the element set's own
    error, more than the 2 m/s archetype burns, so velocity could not tell an included burn apart (_after_burn does).
    """
    red = cast("BlueTrack", row.red_track)   # _no_state, run before this, refused a row without one
    pre = np.asarray(row.hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
    d = float(np.linalg.norm(pre[:3] - red.state_eci_km[:3]))
    return None if d <= START_TOLERANCE_KM else _START_MISMATCH.format(d=d, tol=START_TOLERANCE_KM)


def _failed(series: SeparationSeries) -> str | None:
    return _FAILED.format(k=series.n_failed, n=series.n_samples_run) if series.n_failed > 0 else None


def _unconverged(series: SeparationSeries) -> str | None:
    if series.converged:
        return None
    return _UNCONVERGED.format(hw=series.percentile_half_width_km, tol=CONVERGENCE_TOLERANCE_KM, cap=MAX_SAMPLE_HOURS)


#: Checked in this order before anything runs; the first that speaks refuses the row.
_PRE_RUN_CHECKS: tuple[Callable[[_Row], str | None], ...] = (
    _too_few, _stale, _after_burn, _no_state, _start_mismatch,
)
#: Checked in this order once the series has run.
_POST_RUN_CHECKS: tuple[Callable[[SeparationSeries], str | None], ...] = (_failed, _unconverged)


def _first_refusal[T](subject: T, checks: tuple[Callable[[T], str | None], ...]) -> str | None:
    for check in checks:
        refusal = check(subject)
        if refusal is not None:
            return _refusal(refusal)
    return None


def _floor_s(row: _Row) -> float:
    """A lower bound on a row's cost, known without drawing a sample: its samples times the window and set-up."""
    return row.hypothesis.n_samples * (row.window.span_s + SET_UP_S_PER_SAMPLE)


def _cost_s(row: _Row) -> float:
    """What a row costs: the larger of its samples times the window and what its series integrates, and set-up."""
    n = row.hypothesis.n_samples
    propagated = max(n * row.window.span_s, separation_integration_s(row.hypothesis, row.window))
    return propagated + n * SET_UP_S_PER_SAMPLE


def _cost(rows: Sequence[_Row]) -> float:
    """What *rows* cost together, in sample-hours; their floor alone once that is over the cap.

    The exact cost draws every sample to find its burn time, so a row far over the cap is refused on the floor
    without drawing any: a million samples took 1 s and 238 MB just to be costed. The floor bounds the samples
    drawn to 4,000.

    Measured single-threaded in the venv (Python 3.13, scipy 1.17.1, numpy 2.4.6, 4 CPUs), whole
    evaluate_scenario on a 4 x 4 grid with one row sampled, LEO 300 km unless stated, idle machine. To fit the
    set-up term, before it existed: 58 samples over 10 h (608.7 with set-up) took 9.45 s, 200 over 2.9 h
    (615.8) 8.47 s, 1,000 over 0.5 h (651) 9.05 s, 2,000 over 0.29 h (880.6) 12.11 s, 5,000 over 0.115 h
    (1,325) 17.75 s and 20,000 over 0.028 h (3,560) 49.21 s. Under the cap with it: the Evasive archetype's
    50 over 11.3 h (595.1) 8.80 s, 58 over 9.8 h (596.7) 8.41 and 8.74 s, 200 over 2.8 h (595.6) 8.82 s,
    500 over 1 h (577) 8.97 s, 1,000 over 0.44 h (590.9) 8.90 s, 2,000 over 0.14 h (580.3) 7.58 s, 3,500 over
    0.02 h (595) 7.79 s, 58 over 9.8 h at 550 km 7.42 s, a burn 10.5 h before a 1 h window (595) 6.32 s and
    one after an 11.8 h window (597.5) 1.99 s. The largest allowed evaluation is therefore about 9 s on an
    idle machine, more beside other work. Not timed by any test.
    """
    floor = sum(_floor_s(row) for row in rows) / _SECONDS_PER_HOUR
    return floor if floor > MAX_SAMPLE_HOURS else sum(_cost_s(row) for row in rows) / _SECONDS_PER_HOUR


def _at_span(row: _Row, span_s: float) -> _Row:
    return row._replace(window=row.window._replace(span_s=span_s))


def _longest_tenths(rows: Sequence[_Row]) -> int:
    """The longest horizon, in tenths of an hour, at which *rows* fit under the cap; 0 when none does.

    The cost never falls as the horizon grows, so a bisection over whole tenths finds it. The current horizon,
    rounded up, is over the cap, or this would not be asked.
    """
    fits, over = 0, math.ceil(rows[0].window.span_s / _TENTH_HOUR_S)
    while over - fits > 1:
        mid = (fits + over) // 2
        if _cost([_at_span(row, mid * _TENTH_HOUR_S) for row in rows]) > MAX_SAMPLE_HOURS:
            over = mid
        else:
            fits = mid
    return fits


def _cap_refusal(rows: Sequence[_Row]) -> str | None:
    """Why the rows that would run together are refused, naming what would fit; None when they fit."""
    total = _cost(rows)
    if total <= MAX_SAMPLE_HOURS:
        return None
    counted = f"{len(rows)} hypothesis" if len(rows) == 1 else f"{len(rows)} hypotheses"
    tenths = _longest_tenths(rows)
    advice = _SHORTEN.format(h=tenths / 10) if tenths > 0 else _NO_HORIZON.format(least=_MIN_CONVERGENCE_SAMPLES)
    over = _OVER_CAP.format(
        total=math.ceil(total), set_up=SET_UP_S_PER_SAMPLE / 60.0, rows=counted, cap=MAX_SAMPLE_HOURS,
    )
    return _refusal(over + advice)


def _run(row: _Row, sampler: Sampler) -> RowSampling:
    series = sampler(row.hypothesis, cast("BlueTrack", row.blue_track), row.window)   # _no_state refused None
    refusal = _first_refusal(series, _POST_RUN_CHECKS)
    return RowSampling(series=None, refusal=refusal) if refusal is not None else RowSampling(series, None)


def _eligible_rows(scenario: Scenario) -> list[_Row | None]:
    """A _Row for each action carrying a hypothesis, None for the rest; empty when the scenario cannot be sampled.

    The binding is read only once some action carries a hypothesis, and then
    only for its red and blue element sets.
    """
    if all(a.hypothesis is None for a in scenario.adversary_actions):
        return []
    binding = scenario.binding
    red, blue = (None, None) if binding is None else (binding.red, binding.blue)
    if red is None or blue is None:
        return []
    window = SeparationWindow(start_utc=scenario.epoch_utc, span_s=scenario.horizon_hours * _SECONDS_PER_HOUR)
    blue_track = elset_state(blue.tle, window.start_utc)
    return [
        None if a.hypothesis is None else _Row(
            hypothesis=a.hypothesis.hypothesis, red=red, blue=blue, blue_track=blue_track,
            red_track=elset_state(red.tle, a.hypothesis.hypothesis.epoch_utc), window=window,
        )
        for a in scenario.adversary_actions
    ]


def plan_sampling(scenario: Scenario, sampler: Sampler = run_separation_series) -> tuple[RowSampling | None, ...]:
    """Each adversary row's separation series, or why it was refused; None for a row that is not eligible.

    A row is eligible when its action carries a hypothesis and the scenario
    is bound to a red track and a blue asset. Each eligible row is checked
    before anything runs: at least 50 samples, both orbits current, the red
    element set no newer than the burn, both element sets propagated (blue to
    the scenario epoch, red to the burn) and the hypothesis starting within
    START_TOLERANCE_KM of the bound red track. The rows that pass are costed
    together against MAX_SAMPLE_HOURS; above it every one is refused, naming
    the longest horizon that would fit, and nothing runs. The rest run one at
    a time on this thread, and a series with a failed sample or not converged
    is refused.
    """
    rows = _eligible_rows(scenario)
    if not rows:
        return (None,) * len(scenario.adversary_actions)
    refusals = [None if row is None else _first_refusal(row, _PRE_RUN_CHECKS) for row in rows]
    ready = [row for i, row in enumerate(rows) if row is not None and refusals[i] is None]
    over = _cap_refusal(ready)
    return tuple(None if row is None else _plan_row(row, refusals[i] or over, sampler) for i, row in enumerate(rows))


def _plan_row(row: _Row, refusal: str | None, sampler: Sampler) -> RowSampling:
    """A row refused before anything runs, or its series run and checked."""
    return RowSampling(None, refusal) if refusal is not None else _run(row, sampler)


def _sampled_bases(series: SeparationSeries, horizon_hours: float) -> OutcomeBases:
    n = len(series.approaches)
    return outcome_bases(
        custody_maintained=LOOKUP_BASES.custody_maintained,
        custody_gap_hours=LOOKUP_BASES.custody_gap_hours,
        closest_approach_km=FigureBasis(
            Basis.SAMPLED, _SAMPLED_CA_NOTE.format(n=n, hw=series.percentile_half_width_km, horizon=horizon_hours),
        ),
        time_to_closest_hours=FigureBasis(Basis.SAMPLED, _SAMPLED_TIME_NOTE.format(n=n, horizon=horizon_hours)),
        delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
    )


def _cell_caveat(series: SeparationSeries) -> str:
    n = len(series.approaches)
    caveat = _CELL_CAVEAT.format(n=n, closest=series.closest_sample_km)
    closing = sum(a.at_window_edge and a.tca_s > 0.0 for a in series.approaches)
    return caveat + _EDGE_CAVEAT.format(k=closing, n=n) if closing else caveat


def _sampled_cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, series: SeparationSeries,
) -> OutcomeMetrics:
    """A cell scored on the sampled P5, with its time the earliest TCA at or below it; the rest are lookups."""
    figures = _lookup_figures(adversary, friendly, scenario)._replace(closest_approach_km=series.miss_km_p5)
    return OutcomeMetrics(
        custody_maintained=figures.custody_maintained,
        custody_gap_hours=round(figures.custody_gap_hours, 2),
        closest_approach_km=round(series.miss_km_p5, 1),
        time_to_closest_hours=round(series.earliest_tca_at_or_below_p5_s / _SECONDS_PER_HOUR, 2),
        delta_v_cost_km_s=round(figures.delta_v_km_s, 5),
        composite_score=round(_score(scenario, friendly, figures), 6),
        figure_bases=_sampled_bases(series, scenario.horizon_hours),
        ca_percentiles=series.percentiles,
        ca_std_km=series.miss_km_std,
        ca_samples=len(series.approaches),
        ca_caveat=_cell_caveat(series),
    )


def _refused_cell(metrics: OutcomeMetrics, refusal: str | None) -> OutcomeMetrics:
    """The lookup cell, with the refusal in the cell and in its closest approach's note."""
    note = f"{LOOKUP_BASES.closest_approach_km.note}. {refusal}"
    bases = dataclasses.replace(LOOKUP_BASES, closest_approach_km=FigureBasis(Basis.LOOKUP, note))
    return dataclasses.replace(metrics, figure_bases=bases, ca_refusal=refusal)


def _cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, sampling: RowSampling | None,
) -> OutcomeMetrics:
    if sampling is None:
        return compute_outcome_metrics(adversary, friendly, scenario)
    if sampling.series is None:
        return _refused_cell(compute_outcome_metrics(adversary, friendly, scenario), sampling.refusal)
    return _sampled_cell(adversary, friendly, scenario, sampling.series)


def _row_notes(scenario: Scenario, plan: Sequence[RowSampling | None]) -> tuple[str | None, ...]:
    return tuple(
        UNSAMPLED_ROW_NOTE if a.hypothesis is not None and p is None else None
        for a, p in zip(scenario.adversary_actions, plan, strict=True)
    )


# ── Response ranking ──────────────────────────────────────────────────────────

def rank_responses(
    friendly_responses: list[FriendlyResponse],
    outcome_row: list[OutcomeMetrics],
) -> list[tuple[FriendlyResponse, float]]:
    """Sort friendly responses best→worst for a single adversary action.

    Best = lowest composite score.
    """
    pairs = [(fr, om.composite_score) for fr, om in zip(friendly_responses, outcome_row, strict=True)]
    return sorted(pairs, key=lambda x: x[1])


def find_robust_response(
    scenario: Scenario,
    outcome_matrix: list[list[OutcomeMetrics]],
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
) -> FriendlyResponse:
    """Select the robust best response across all adversary actions.

    Parameters
    ----------
    scenario:
        The evaluated scenario.
    outcome_matrix:
        outcome_matrix[i][j] for adversary i, friendly j.
    strategy:
        MINIMAX  — minimise the maximum (worst-case) composite score.
        EXPECTED_VALUE — minimise expected score weighted by adversary probabilities.
        MINIMIN  — minimise the minimum (best-case) composite score: optimistic,
                   not robust.

    Returns
    -------
    The ``FriendlyResponse`` that is robust under the chosen strategy.
    """
    n_adversary = len(scenario.adversary_actions)
    n_friendly  = len(scenario.friendly_responses)

    if n_friendly == 0:
        raise ValueError("No friendly responses to select from")

    scores = [0.0] * n_friendly

    if strategy == SelectorStrategy.MINIMAX:
        for j in range(n_friendly):
            scores[j] = max(outcome_matrix[i][j].composite_score for i in range(n_adversary))
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    elif strategy == SelectorStrategy.EXPECTED_VALUE:
        total_p = sum(a.probability for a in scenario.adversary_actions)
        if total_p <= 0:
            total_p = 1.0
        for j in range(n_friendly):
            scores[j] = sum(
                (scenario.adversary_actions[i].probability / total_p) * outcome_matrix[i][j].composite_score
                for i in range(n_adversary)
            )
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    else:  # MINIMIN: minimise the best-case score, the optimistic rule
        for j in range(n_friendly):
            scores[j] = min(outcome_matrix[i][j].composite_score for i in range(n_adversary))
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    return scenario.friendly_responses[best_j]


# ── Top-level evaluation ───────────────────────────────────────────────────────

def _binding_inputs(scenario: Scenario) -> tuple[InputRef, ...]:
    """Each bound element set as a provenance input, so a bound result traces to its orbits (F-121)."""
    if scenario.binding is None:
        return ()
    return tuple(tle_input(f"{b.side} {b.stk_name}", b.tle, b.epoch) for b in scenario.binding.bound)


def _hypothesis_inputs(scenario: Scenario) -> tuple[InputRef, ...]:
    """Each adversary action's hypothesis as a provenance input, dated at its burn (SPC-111)."""
    return tuple(
        dataclasses.replace(
            value_input(f"hypothesis {a.id} ({a.hypothesis.source.value})", a.hypothesis.recorded()),
            epoch=a.hypothesis.hypothesis.epoch_utc,
        )
        for a in scenario.adversary_actions
        if a.hypothesis is not None
    )


def evaluate_scenario(
    scenario: Scenario,
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
    *,
    sampler: Sampler = run_separation_series,
) -> ScenarioResult:
    """Evaluate all (adversary × friendly) combinations and return a ranked result.

    Parameters
    ----------
    scenario:
        Fully populated Scenario dataclass.
    strategy:
        Selector strategy for the robust recommendation.
    sampler:
        Runs a row's separation series (SPC-112); a test passes a fake. Only
        a row plan_sampling finds eligible calls it.

    Returns
    -------
    ScenarioResult with full outcome matrix, per-adversary rankings, and the
    robust best response.
    """
    if not scenario.adversary_actions:
        raise ValueError("Scenario must have at least one adversary action")
    if not scenario.friendly_responses:
        raise ValueError("Scenario must have at least one friendly response")

    t0 = time.monotonic()

    # Build outcome matrix: a lookup in every cell but those of a row plan_sampling sampled or refused
    plan = plan_sampling(scenario, sampler)
    outcome_matrix = [
        [_cell(adversary, friendly, scenario, sampling) for friendly in scenario.friendly_responses]
        for adversary, sampling in zip(scenario.adversary_actions, plan, strict=True)
    ]

    # Rank per adversary action
    ranked_per_adversary = [
        rank_responses(scenario.friendly_responses, outcome_matrix[i])
        for i in range(len(scenario.adversary_actions))
    ]

    # Robust selection
    robust_response = find_robust_response(scenario, outcome_matrix, strategy)

    wall_time = time.monotonic() - t0

    return ScenarioResult(
        scenario=scenario,
        outcome_matrix=outcome_matrix,
        ranked_per_adversary=ranked_per_adversary,
        robust_best_response=robust_response,
        robust_strategy=strategy,
        computation_time_s=round(wall_time, 4),
        provenance=provenance(
            [value_input("scenario", scenario), *_binding_inputs(scenario), *_hypothesis_inputs(scenario)],
        ),
        row_notes=_row_notes(scenario, plan),
    )
