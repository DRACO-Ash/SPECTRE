"""Threat Understanding: a threat range that narrows as SPECTRE learns the satellite.

The owner's sentence (3 November 2026): "The more we understand a satellite
and its capabilities and its manoeuvres and its interactions, the more we
understand its threat score when SPECTRE returns a result." The concept is
docs/threat_confidence_concept.md; this module is its section 4.

Each piece of evidence about a satellite is an :class:`EvidenceItem`, graded
twice, as Knowledge-Based Trust separates them: the source on the NATO
Admiralty scale, and our own processing chain (the extraction). Its
reliability ``q`` is the product of the two with its freshness, capped where
the adversary controls the claim. Items that share a source chain form one
group and count once, so four figures read from one element-set history are
one piece of evidence, not four. Coverage of each dimension (Identity,
Capability, Behaviour, Interactions) is a noisy-OR across its groups, so it
never falls when an independent group is added.

A reading (a floor raised or a ceiling lowered) applies only when its
dimension is earned, its own q is high enough and it is the strongest of its
group: a weaker copy is folded, its reading as well as its coverage. The
floor is what the evidence proves at least; the ceiling is what it cannot
yet rule out; ACCESS, the geometry, bounds both. Suspicion persists and
trust decays: a floor earned when it was judged stays until a later burn is
judged UNUSUAL or UNPRECEDENTED (a ROUTINE burn lowers nothing), while a
ceiling decays with its evidence. An impaired status contradicted by a newer
burn is voided and named as possible deception. A floor above a ceiling,
both in effect at the same instant, is a conflict: both readings go and the
range is recomputed from the rest, so a conflict can only widen the range.

Understanding follows PHIA's Analytical Confidence Rating: three categories,
information base, analytical rigour, and complexity and volatility, each
with explicit criteria, and the weakest governs. The data mode and a manual
element set cap it. Orbital geometry never counts towards it. The verdict is
the legacy reading clamped to the range, or the ceiling when Understanding
is LOW or the range too wide to call.

The adapters at the end (SPC-165) read what SPECTRE already holds, the
intel record, the GCAT entry and the element-set history with its Pattern
of Life reading, and build the items of section 5; a manoeuvre-attributable
approach from ``interaction_graph`` becomes Interactions evidence (SPC-172).
The sweep runs the model beside the legacy verdict, in shadow (SPC-166),
and lets it move one thing live: decide-by is withheld only on a computed
MINIMAL ceiling the evidence has earned (SPC-167), never on a recorded
status alone.

Every weight and threshold here is tuned, not sourced, and says so.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum, IntEnum
from typing import Any

from spectre.domain.custody import Custody, age_text
from spectre.domain.interaction_graph import Edge
from spectre.domain.manoeuvre_calibration import Posture
from spectre.domain.normality import Normality, burns_from_views, judge_burn
from spectre.domain.pol_assessment import STANDARD_GRAVITY_M_S2, anomaly_risk_level
from spectre.domain.provenance import Basis, weakest
from spectre.domain.threat_assessment import PROPELLANT_SPENT_PCT, Band, CapabilityEvidence
from spectre.domain.warning_change import Change

__all__ = [
    "ACTION_LINE",
    "ASSESSED_LABEL_EXTRACTION",
    "ASSUMED_FIGURE_EXTRACTION",
    "CATALOGUE_FIELD_EXTRACTION",
    "CREDIBILITY",
    "DETECTION_EXTRACTION",
    "EARNED",
    "MANUAL_EXTRACTION",
    "MANUFACTURABLE_CAP",
    "PARTIAL",
    "PULL_HISTORY",
    "PROVIDER_GRADES",
    "RECORD_DATE_FIELD",
    "ROUTINE_CAP",
    "SOURCE_RELIABILITY",
    "UNATTRIBUTED",
    "Advice",
    "BurnSignal",
    "CollectionAdvice",
    "Cue",
    "Depth",
    "Dimension",
    "EvidenceItem",
    "HeldBurn",
    "HistorySignals",
    "LedgerRow",
    "Situation",
    "Status",
    "Support",
    "ThreatRange",
    "ThreatUnderstanding",
    "Understanding",
    "UnderstandingRating",
    "Verdict",
    "assess",
    "burn_extraction",
    "collection_advice",
    "coverage",
    "cue_text",
    "cues",
    "depth",
    "earned_incapacity",
    "freshness",
    "gcat_items",
    "half_life_days",
    "history_items",
    "history_signals",
    "intel_items",
    "interaction_items",
    "landing_cues",
    "manual_extraction",
    "missing",
    "provider_grade",
    "reading_text",
    "record_date",
    "reliability",
    "threat_range",
    "threat_sentence",
    "understand",
    "verdict_for",
    "window_custody",
    "with_history",
    "with_record",
]

_SECONDS_PER_DAY = 86400.0

# Admiralty source reliability, the letter, as a weight. A: own or allied
# sensor, analyst-adjudicated. B: the 18 SDS catalogue through UDL, and GCAT.
# C: a commercial provider, and an open-source intel record. D: declared by
# the object's operator. E: unreliable. F: cannot be judged, read as D.
# Tuned, not sourced.
SOURCE_RELIABILITY: dict[str, float] = {"A": 0.9, "B": 0.8, "C": 0.6, "D": 0.3, "E": 0.1, "F": 0.3}

# Admiralty information credibility, the digit, as a weight. 1: confirmed by
# an independent source. 6: cannot be judged. Tuned, not sourced.
CREDIBILITY: dict[int, float] = {1: 1.0, 2: 0.85, 3: 0.6, 4: 0.4, 5: 0.2, 6: 0.3}

# Extraction: how far our own chain can be trusted to have read the source
# right. The burn detection grade from astro/dv_estimation.py (HIGH and
# MODERATE from _grade_confidence, LOW and REJECT from _disqualifying_verdict).
# Tuned, not sourced.
DETECTION_EXTRACTION: dict[str, float] = {"HIGH": 0.9, "MODERATE": 0.6, "LOW": 0.3, "REJECT": 0.0}
# A figure resting on a regime Isp or mass-fraction assumption. Tuned, not sourced.
ASSUMED_FIGURE_EXTRACTION: float = 0.5
# An analyst's assessed label (role, threat level, status). Tuned, not sourced.
ASSESSED_LABEL_EXTRACTION: float = 0.5
# A catalogue field read directly. Tuned, not sourced.
CATALOGUE_FIELD_EXTRACTION: float = 1.0
# A burn across a long gap, or a fit whose residual exceeds its regime's
# threshold, is read at half the extraction. Tuned, not sourced.
_DEGRADED_EXTRACTION_FACTOR: float = 0.5
# A manual element set, by the confidence the operator stated on the sweep
# form (web/routes/threat.py _CONFIDENCES), strongest first. Tuned, not sourced.
MANUAL_EXTRACTION: dict[str, float] = {
    "CONFIRMED": 1.0, "HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3, "UNCONFIRMED": 0.1,
}
_WEAKEST_MANUAL = "UNCONFIRMED"

# The most an item the adversary controls can be worth: a declared status,
# a declared mission, a NOTSO filing. Below EARNED, so one alone can never
# earn a dimension. Tuned, not sourced.
MANUFACTURABLE_CAP: float = 0.3
# The most a ROUTINE normality verdict can be worth, because the baseline it
# is judged against is the object's own behaviour. Tuned, not sourced.
ROUTINE_CAP: float = 0.5

# Half-lives in days, by dimension, and for Behaviour by regime. Behaviour is
# shortest in LEO, where an object can change its pattern in days. Tuned, not
# sourced.
_HALF_LIFE_DAYS: dict[str, float] = {"IDENTITY": 365.0, "CAPABILITY": 90.0, "INTERACTIONS": 30.0}
_BEHAVIOUR_HALF_LIFE_DAYS: dict[str, float] = {"GEO": 60.0, "LEO": 14.0}
_BEHAVIOUR_HALF_LIFE_OTHERWISE_DAYS: float = 30.0
# An undated item is taken as this many half-lives old. Tuned, not sourced.
_UNDATED_AGE_HALF_LIVES: float = 1.0
# Query Deserves Freshness: Capability and Behaviour evidence from before the
# latest burn judged UNUSUAL or UNPRECEDENTED is worth this fraction. Tuned,
# not sourced.
_QDF_RESET: float = 0.5
_HOSTILE = frozenset({Normality.UNUSUAL, Normality.UNPRECEDENTED})

# A dimension is earned at this coverage and partial at the second. Tuned, not sourced.
EARNED: float = 0.5
PARTIAL: float = 0.25
# A reading applies only when its own q reaches this. Tuned, not sourced.
_READING_Q: float = 0.25
# The lowest ceiling an impaired status can set (I5). Tuned, not sourced.
_IMPAIRED_CEILING_FLOOR: Band = Band.MEDIUM
# The highest floor a prior (an Identity reading) or an uncalibrated lookup, such as
# the anomaly index rung, can set. Tuned, not sourced.
_PRIOR_FLOOR_CAP: Band = Band.MEDIUM
# Everything the adversary controls is declared by one source, the object's operator,
# so manufacturable items share this root whatever chain they arrived by (section 2.4).
_OPERATOR_ROOT = "declared by the operator"
# A range spanning this many bands or more is too wide to call a point inside it. Tuned, not sourced.
_WIDE_RANGE_BANDS: int = 4


class Dimension(Enum):
    """What an item tells us about the satellite. ACCESS is the question, not a dimension."""

    IDENTITY = "Identity"            # who it is
    CAPABILITY = "Capability"        # what it can still do
    BEHAVIOUR = "Behaviour"          # how it manoeuvres
    INTERACTIONS = "Interactions"    # what it has approached


#: Freshness reset by the latest hostile burn applies to these only.
_RESET_DIMENSIONS = frozenset({Dimension.CAPABILITY, Dimension.BEHAVIOUR})


class Depth(Enum):
    """How much of a dimension is covered: the strip shows it filled, half-filled or empty."""

    NONE = "not earned"
    PARTIAL = "partial"
    EARNED = "earned"


@dataclass(frozen=True)
class HeldBurn:
    """A confirmed burn in the held history, and the normality verdict on it."""

    epoch: datetime
    normality: Normality


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence about a satellite, graded by its source and by our chain.

    *floor_to* is the floor this item would raise the threat to, *ceiling_to*
    the ceiling it would lower it to; at most one is set. *derived_from* is
    the root of its source chain: items sharing a dimension and a root are
    one group and count once. What an item may claim is refused at
    construction (section 4.6, 5.1 and 5.2), so no adapter can build a wrong one.
    """

    dimension: Dimension
    label: str
    derived_from: str
    source_grade: str                 # Admiralty letter, A to F
    credibility: int                  # Admiralty digit, 1 to 6
    extraction: float                 # our processing chain, 0 to 1
    basis: Basis
    observed_at: datetime | None
    floor_to: Band | None = None
    ceiling_to: Band | None = None
    manufacturable: bool = False      # the adversary controls the claim
    controlled: bool = False          # own, allied or 18 SDS
    routine: bool = False             # a ROUTINE normality verdict: coverage only
    impaired_status: bool = False     # a status saying the object cannot manoeuvre
    note: str = ""

    def __post_init__(self) -> None:
        problems = (
            (self.source_grade not in SOURCE_RELIABILITY, "source grade must be an Admiralty letter, A to F"),
            (self.credibility not in CREDIBILITY, "credibility must be an Admiralty digit, 1 to 6"),
            (not 0.0 <= self.extraction <= 1.0, "extraction must be between 0 and 1"),
            (self.floor_to is not None and self.ceiling_to is not None, "an item raises the floor or lowers "
             "the ceiling, not both"),
            (self.dimension is Dimension.CAPABILITY and self.floor_to is not None,
             "Capability only lowers the ceiling; it never raises the floor"),
            (self.dimension is not Dimension.CAPABILITY and self.ceiling_to is not None,
             "only Capability lowers the ceiling"),
            (self.routine and self.has_reading, "a routine verdict is coverage only and carries no reading"),
            (self.impaired_status and self.dimension is not Dimension.CAPABILITY,
             "an impaired status is Capability evidence"),
            (self.manufacturable and self.has_reading and not self.impaired_status,
             "a claim the adversary controls is coverage only; of those, only an impaired status carries a reading"),
            (_band_key(self.floor_to) > int(_PRIOR_FLOOR_CAP) and self.dimension is Dimension.IDENTITY,
             "a prior never raises the floor above MEDIUM"),
            (_band_key(self.floor_to) > int(_PRIOR_FLOOR_CAP) and self.basis is Basis.LOOKUP,
             "an uncalibrated lookup never raises the floor above MEDIUM"),
        )
        for failed, message in problems:
            if failed:
                raise ValueError(f"{self.label}: {message}")

    @property
    def grade(self) -> str:
        """The Admiralty grade as the ledger shows it, for example "B2"."""
        return f"{self.source_grade}{self.credibility}"

    @property
    def group(self) -> tuple[Dimension, str]:
        """The independence key: the dimension and the source chain's root.

        Every manufacturable item is declared by the object's operator, one
        source, so together they count once and can never earn a dimension.
        """
        return self.dimension, _OPERATOR_ROOT if self.manufacturable else self.derived_from

    @property
    def has_reading(self) -> bool:
        return self.floor_to is not None or self.ceiling_to is not None


def _band_key(band: Band | None) -> int:
    return -1 if band is None else int(band)


def _reading_rank(item: EvidenceItem) -> int:
    """How far an item's reading would narrow the range: 0 for none, more for a higher floor or a lower ceiling."""
    if item.floor_to is not None:
        return int(item.floor_to) + 1
    if item.ceiling_to is not None:
        return len(Band) - int(item.ceiling_to)
    return 0


def burn_extraction(grade: str, *, long_gap: bool = False, poor_fit: bool = False) -> float:
    """Extraction for a burn figure, from its detection grade, halved for a long gap or a poor fit."""
    if grade not in DETECTION_EXTRACTION:
        raise ValueError(f"unknown detection grade {grade!r}")
    value = DETECTION_EXTRACTION[grade]
    for degraded in (long_gap, poor_fit):
        if degraded:
            value *= _DEGRADED_EXTRACTION_FACTOR
    return value


def manual_extraction(confidence: str | None) -> float:
    """Extraction for a manual element set, by the operator's stated confidence; unstated reads as weakest."""
    return MANUAL_EXTRACTION.get((confidence or "").strip().upper(), MANUAL_EXTRACTION[_WEAKEST_MANUAL])


def half_life_days(dimension: Dimension, regime: str) -> float:
    """How many days it takes evidence in *dimension* to lose half its weight."""
    if dimension is Dimension.BEHAVIOUR:
        return _BEHAVIOUR_HALF_LIFE_DAYS.get(regime.strip().upper(), _BEHAVIOUR_HALF_LIFE_OTHERWISE_DAYS)
    return _HALF_LIFE_DAYS[dimension.name]


def _reset(item: EvidenceItem, at: datetime, burns: Iterable[HeldBurn]) -> float:
    """Half, for Capability and Behaviour evidence from before the latest hostile burn by *at*."""
    if item.dimension not in _RESET_DIMENSIONS:
        return 1.0
    hostile = [b.epoch for b in burns if b.normality in _HOSTILE and b.epoch <= at]
    if not hostile:
        return 1.0
    # An undated item is older than any held burn, as the void rule reads it.
    before = item.observed_at is None or item.observed_at < max(hostile)
    return _QDF_RESET if before else 1.0


def freshness(item: EvidenceItem, at: datetime, *, burns: Iterable[HeldBurn] = (), regime: str = "GEO") -> float:
    """f_i at *at*: halves every half-life, an undated item one half-life old, reset by a hostile burn."""
    half_life = half_life_days(item.dimension, regime)
    if item.observed_at is None:
        age_days = _UNDATED_AGE_HALF_LIVES * half_life
    else:
        # An epoch a little ahead of the clock is fresh, not fresher.
        age_days = max(0.0, (at - item.observed_at).total_seconds() / _SECONDS_PER_DAY)
    decay: float = 0.5 ** (age_days / half_life)
    return decay * _reset(item, at, burns)


def _cap(item: EvidenceItem) -> float:
    caps = [1.0]
    if item.manufacturable:
        caps.append(MANUFACTURABLE_CAP)
    if item.routine:
        caps.append(ROUTINE_CAP)
    return min(caps)


def reliability(item: EvidenceItem, at: datetime, *, burns: Iterable[HeldBurn] = (), regime: str = "GEO") -> float:
    """q_i = min(cap_i, r_src x r_cred x r_ext x f_i), between 0 and 1."""
    raw = (SOURCE_RELIABILITY[item.source_grade] * CREDIBILITY[item.credibility] * item.extraction
           * freshness(item, at, burns=burns, regime=regime))
    return min(_cap(item), raw)


def _noisy_or(values: Iterable[float]) -> float:
    """1 - prod(1 - q), accumulated so one group's coverage is exactly its q, not q plus rounding."""
    covered = 0.0
    for value in values:
        covered += value - covered * value
    return covered


def _group_bests(qs: Iterable[tuple[EvidenceItem, float]]) -> dict[tuple[Dimension, str], float]:
    best: dict[tuple[Dimension, str], float] = {}
    for item, q in qs:
        best[item.group] = max(q, best.get(item.group, 0.0))
    return best


def _cover(bests: dict[tuple[Dimension, str], float]) -> dict[Dimension, float]:
    by_dimension: dict[Dimension, list[float]] = {d: [] for d in Dimension}
    for (dimension, _root), q in bests.items():
        by_dimension[dimension].append(q)
    # Sorted, so the product, and the coverage, does not depend on arrival order.
    return {d: _noisy_or(sorted(qs)) for d, qs in by_dimension.items()}


def _visible(item: EvidenceItem, at: datetime) -> bool:
    return item.observed_at is None or item.observed_at <= at


def coverage(items: Iterable[EvidenceItem], at: datetime, *, burns: Iterable[HeldBurn] = (),
             regime: str = "GEO") -> dict[Dimension, float]:
    """u_d for every dimension at *at*: the strongest item per group, noisy-OR across groups."""
    held = tuple(burns)
    qs = [(i, reliability(i, at, burns=held, regime=regime)) for i in items if _visible(i, at)]
    return _cover(_group_bests(qs))


def depth(u: float) -> Depth:
    """Earned, partial or none, from a dimension's coverage."""
    if u >= EARNED:
        return Depth.EARNED
    return Depth.PARTIAL if u >= PARTIAL else Depth.NONE


class Understanding(IntEnum):
    """How well founded the threat range is, ordered so the weakest can be taken with ``min``."""

    LOW = 0
    MODERATE = 1
    HIGH = 2


class Status(Enum):
    """What became of an item, as the ledger's status column reads it."""

    COUNTED = "counted"
    FOLDED = "folded"
    PERSISTING = "persisting"
    DECAYED = "decayed"
    BELOW_THRESHOLD = "below threshold"
    UNCORROBORATED = "uncorroborated"
    VOIDED = "voided: possible deception"
    CONFLICT = "in conflict"


@dataclass(frozen=True)
class Situation:
    """What is known about the object besides the evidence items.

    *access* is the geometry's band, the ceiling no evidence can raise.
    *legacy* is today's ``min(ACCESS, capability)``, ``None`` when there is
    no capability evidence. *burns* are the confirmed burns in the held
    history with their normality verdicts. *newest_elset_at* is the newest
    element set held, and *elset_limit_hours* its regime's staleness limit
    (web/elsets.py ``limit_hours_for_regime``). *data_mode* is the element
    sets' recorded mode; ``None`` means it was not recorded. *custody* and
    *history_truncated* have no default: an adapter that forgot them would
    otherwise be read as holding the object on a whole history, the strongest
    case, so it must state them.
    """

    now: datetime
    access: Band
    _: KW_ONLY
    custody: Custody
    history_truncated: bool
    legacy: Band | None = None
    regime: str = "GEO"
    burns: tuple[HeldBurn, ...] = ()
    sees_routine_station_keeping: bool = False
    newest_elset_at: datetime | None = None
    elset_limit_hours: float = 72.0
    data_mode: str | None = None
    manual_confidence: str | None = None
    #: The floor the intel record would set once an analyst dates and sources
    #: it (section 5.1): MEDIUM when its threat level is HIGH or CRITICAL.
    record_prior: Band | None = None


@dataclass(frozen=True)
class UnderstandingRating:
    """Understanding and the three categories behind it; the weakest governs.

    *reasons* gives, for each category or cap short of HIGH, what is missing.
    *governing* names those at the final level. *statement* is the AnCR-form
    sentence the operator reads; it never names the threat.
    """

    level: Understanding
    information_base: Understanding
    rigour: Understanding
    volatility: Understanding
    governing: tuple[str, ...]
    reasons: tuple[tuple[str, str], ...]
    statement: str


@dataclass(frozen=True)
class Support:
    """What a bound of the range rests on, as Analytical Rigour judges it."""

    label: str
    basis: Basis
    controlled: bool


#: The ceiling when no reading lowers it: the geometry, computed, but from no source group.
_ACCESS_SUPPORT = Support(label="access", basis=Basis.COMPUTED, controlled=False)
#: Basis strength, weakest first, as provenance.Basis declares it.
_BASIS_RANK: dict[Basis, int] = {basis: rank for rank, basis in enumerate(Basis)}


@dataclass(frozen=True)
class LedgerRow:
    """One row of "What it rests on": an item, its q now, and what became of it."""

    item: EvidenceItem
    q: float
    age_days: float | None
    counted: bool             # the strongest of its group, so it counts towards coverage
    applied: bool             # its reading is in effect
    status: Status
    note: str


@dataclass(frozen=True)
class ThreatRange:
    """The threat range, the coverage behind it and the ledger of every item.

    *lapsed_ceilings* are ceiling readings judged once that have since
    decayed. Analytical Rigour counts them as though they still set the
    ceiling, so letting a reading lapse can lower rigour but never raise it.
    """

    floor: Band
    ceiling: Band
    coverage: dict[Dimension, float]
    ledger: tuple[LedgerRow, ...]
    conflicts: tuple[tuple[str, str], ...]      # (floor item, ceiling item)
    possible_deception: tuple[str, ...]
    reobserve: tuple[str, ...]
    floor_support: Support | None             # None while no reading sets the floor
    ceiling_support: Support
    lapsed_ceilings: tuple[Support, ...]

    @property
    def bands(self) -> int:
        """How many bands the range spans, MINIMAL to CRITICAL being 5."""
        return int(self.ceiling) - int(self.floor) + 1


@dataclass(frozen=True)
class Verdict:
    """The assessed point inside the range, and the band the verdict reads."""

    assessed: Band
    band: Band
    at_ceiling: bool          # Understanding LOW or a wide range: the verdict is the ceiling


def verdict_for(legacy: Band, floor: Band, ceiling: Band, understanding: Understanding) -> Verdict:
    """The legacy reading clamped to the range; the ceiling when Understanding is LOW or the range is wide."""
    if floor > ceiling:
        raise ValueError("a range with its floor above the ceiling")
    assessed = Band(min(max(legacy, floor), ceiling))
    at_ceiling = understanding is Understanding.LOW or int(ceiling) - int(floor) + 1 >= _WIDE_RANGE_BANDS
    return Verdict(assessed=assessed, band=ceiling if at_ceiling else assessed, at_ceiling=at_ceiling)


def _canonical(item: EvidenceItem) -> tuple[object, ...]:
    """A total order on items, so the result does not depend on the order they arrive in."""
    epoch = float("-inf") if item.observed_at is None else item.observed_at.timestamp()
    return (
        list(Dimension).index(item.dimension), item.derived_from, item.label, epoch, item.source_grade,
        item.credibility, item.extraction, item.basis.value, _band_key(item.floor_to), _band_key(item.ceiling_to),
        item.manufacturable, item.controlled, item.routine, item.impaired_status, item.note,
    )


class _Engine:
    """The rules of sections 4.4 to 4.7 over one fixed, canonically ordered list of items.

    Items are referred to by index, so two identical items stay two rows.
    """

    def __init__(self, items: tuple[EvidenceItem, ...], situation: Situation) -> None:
        self.items = items
        self.situation = situation
        self.now = situation.now
        self.burns = tuple(b for b in situation.burns if b.epoch <= situation.now)
        # An epoch a little ahead of the clock counts as observed now.
        self.epochs = tuple(None if i.observed_at is None else min(i.observed_at, self.now) for i in items)
        dated = {e for e in self.epochs if e is not None}
        # Coverage only falls between these instants, so a reading earned at any time
        # since its epoch was earned at one of them.
        self.steps = tuple(sorted(dated | {b.epoch for b in self.burns} | {self.now}))
        self.corroborated = (not self.burns and situation.custody is Custody.HELD
                             and situation.sees_routine_station_keeping)
        self._q: dict[tuple[int, datetime], float] = {}
        self._vouching: dict[tuple[frozenset[int], datetime], dict[Dimension, float]] = {}
        self._leaders: dict[datetime, dict[tuple[Dimension, str], int]] = {}
        self.voided = frozenset(i for i in range(len(items)) if self._is_voided(i))
        self.live = frozenset(range(len(items))) - self.voided

    def q(self, index: int, at: datetime) -> float:
        key = (index, at)
        if key not in self._q:
            self._q[key] = reliability(self.items[index], at, burns=self.burns, regime=self.situation.regime)
        return self._q[key]

    def visible(self, index: int, at: datetime) -> bool:
        epoch = self.epochs[index]
        return epoch is None or epoch <= at

    def vouching(self, members: frozenset[int], at: datetime) -> dict[Dimension, float]:
        """Coverage that can earn a dimension for a reading: a ROUTINE verdict vouches for nothing."""
        key = (members, at)
        if key not in self._vouching:
            qs = [(self.items[i], self.q(i, at)) for i in sorted(members)
                  if self.visible(i, at) and not self.items[i].routine]
            self._vouching[key] = _cover(_group_bests(qs))
        return self._vouching[key]

    def leaders(self, at: datetime) -> dict[tuple[Dimension, str], int]:
        """The member of each group whose reading may apply at *at*: the strongest held then.

        A weaker copy is folded, its reading with its coverage (I2). On equal q
        the stronger reading leads, so a coverage-only figure from the same
        history never displaces it by the order items arrive in. A ROUTINE
        verdict leads nothing, as it vouches for nothing (I9).
        """
        if at not in self._leaders:
            best: dict[tuple[Dimension, str], int] = {}
            for i in sorted(self.live):
                item = self.items[i]
                if item.routine or not self.visible(i, at):
                    continue
                key = (self.q(i, at), _reading_rank(item))
                held = best.get(item.group)
                if held is None or key > (self.q(held, at), _reading_rank(self.items[held])):
                    best[item.group] = i
            self._leaders[at] = best
        return self._leaders[at]

    def bests(self, members: frozenset[int]) -> dict[tuple[Dimension, str], int]:
        """The strongest item of each group now, for coverage; the first in canonical order on a tie."""
        best: dict[tuple[Dimension, str], int] = {}
        for i in sorted(members):
            group = self.items[i].group
            if group not in best or self.q(i, self.now) > self.q(best[group], self.now):
                best[group] = i
        return best

    def coverage(self, members: frozenset[int]) -> dict[Dimension, float]:
        return _cover({g: self.q(i, self.now) for g, i in self.bests(members).items()})

    def applicable(self, index: int, at: datetime, members: frozenset[int]) -> bool:
        """Section 4.6 at *at*: its group's leader, its own q high enough, its dimension earned."""
        item = self.items[index]
        if self.leaders(at).get(item.group) != index or (item.impaired_status and not self.corroborated):
            return False
        return self.q(index, at) >= _READING_Q and self.vouching(members, at)[item.dimension] >= EARNED

    def superseded(self, index: int, at: datetime) -> bool:
        """A hostile burn judged after the item, by *at*: a floor from before it no longer persists.

        Only UNUSUAL or UNPRECEDENTED supersedes. A ROUTINE burn lowers nothing
        (section 5.3, section 8, I9): routine-looking station keeping is how an
        adversary would feign benignity.
        """
        epoch = self.epochs[index]
        return any(b.normality in _HOSTILE and b.epoch <= at and (epoch is None or b.epoch > epoch)
                   for b in self.burns)

    def in_effect(self, index: int, at: datetime, members: frozenset[int]) -> bool:
        """Its reading holds at *at*: applicable then, or a floor judged earlier and not yet superseded."""
        if self.applicable(index, at, members):
            return True
        return (self.items[index].floor_to is not None and not self.superseded(index, at)
                and any(self.applicable(index, s, members) for s in self.steps if s < at))

    def _is_voided(self, index: int) -> bool:
        """An impaired status older than a held confirmed burn; an undated record is older than any."""
        epoch = self.epochs[index]
        return self.items[index].impaired_status and any(epoch is None or b.epoch > epoch for b in self.burns)

    def ceiling_of(self, index: int) -> Band:
        item = self.items[index]
        band = item.ceiling_to if item.ceiling_to is not None else Band.CRITICAL
        return max(band, _IMPAIRED_CEILING_FLOOR) if item.impaired_status else band

    def conflicts(self) -> tuple[tuple[int, int], ...]:
        """A floor above a ceiling, both in effect at the same instant.

        A ceiling that had decayed before the floor was judged is not in
        effect beside it, so it conflicts with nothing. A pair once found
        stays found: ageing cannot dissolve a conflict and raise Understanding (I4).
        """
        readings = [i for i in sorted(self.live) if self.items[i].has_reading]
        found: set[tuple[int, int]] = set()
        for at in self.steps:
            held = [i for i in readings if self.in_effect(i, at, self.live)]
            floors = [i for i in held if self.items[i].floor_to is not None]
            ceilings = [i for i in held if self.items[i].ceiling_to is not None]
            found.update((f, c) for f in floors for c in ceilings
                         if _band_key(self.items[f].floor_to) > int(self.ceiling_of(c)))
        return tuple(sorted(found))


@dataclass(frozen=True)
class _Outcome:
    """The sets one evaluation produced, for the ledger to read."""

    pairs: tuple[tuple[int, int], ...]
    partners: dict[int, tuple[int, ...]]
    rest: frozenset[int]
    judged: frozenset[int]
    current: frozenset[int]
    in_effect: frozenset[int]
    bests: dict[tuple[Dimension, str], int]


def _evaluate(engine: _Engine) -> _Outcome:
    pairs = engine.conflicts()
    partners: dict[int, tuple[int, ...]] = {}
    for f, c in pairs:
        partners[f] = (*partners.get(f, ()), c)
        partners[c] = (*partners.get(c, ()), f)
    # Recomputed from the rest, without the conflicting items' coverage either, so a
    # conflicting item cannot earn a dimension for another reading. Its group goes with
    # it: a copy of a conflicting reading is no less in conflict (I2).
    removed = {engine.items[i].group for i in partners}
    rest = frozenset(i for i in engine.live if engine.items[i].group not in removed)
    readings = [i for i in sorted(rest) if engine.items[i].has_reading]
    judged = frozenset(i for i in readings if any(engine.applicable(i, t, rest) for t in engine.steps))
    in_effect = frozenset(i for i in readings if engine.in_effect(i, engine.now, rest))
    current = frozenset(i for i in in_effect if engine.applicable(i, engine.now, rest))
    return _Outcome(pairs, partners, rest, judged, current, in_effect, engine.bests(rest))


def _bounds(engine: _Engine, outcome: _Outcome) -> tuple[Band, Band]:
    floors = [b for i in outcome.in_effect if (b := engine.items[i].floor_to) is not None]
    ceilings = [engine.ceiling_of(i) for i in outcome.in_effect if engine.items[i].ceiling_to is not None]
    access = engine.situation.access
    floor_cap = max(floors, default=Band.MINIMAL)
    ceiling_cap = min(ceilings, default=Band.CRITICAL)
    return Band(min(access, floor_cap)), Band(min(access, ceiling_cap))


class _Ledger:
    """Writes one row per item, in canonical order."""

    def __init__(self, engine: _Engine, outcome: _Outcome) -> None:
        self.engine = engine
        self.outcome = outcome
        self.counted = frozenset(outcome.bests.values())
        self.vouching = engine.vouching(outcome.rest, engine.now)
        self.leaders = engine.leaders(engine.now)

    def rows(self) -> tuple[LedgerRow, ...]:
        return tuple(self.row(i) for i in range(len(self.engine.items)))

    def row(self, index: int) -> LedgerRow:
        status, note = self.status(index)
        epoch = self.engine.epochs[index]
        age = None if epoch is None else (self.engine.now - epoch).total_seconds() / _SECONDS_PER_DAY
        return LedgerRow(item=self.engine.items[index], q=self.engine.q(index, self.engine.now), age_days=age,
                         counted=index in self.counted, applied=index in self.outcome.in_effect,
                         status=status, note=note)

    def label(self, index: int) -> str:
        return self.engine.items[index].label

    def status(self, index: int) -> tuple[Status, str]:
        if index in self.engine.voided:
            return Status.VOIDED, "voided: possible deception, a confirmed burn newer than the record is held"
        if index in self.outcome.partners:
            names = ", ".join(self.label(p) for p in self.outcome.partners[index])
            return Status.CONFLICT, f"in conflict with {names}"
        if index not in self.outcome.rest:
            party = next(p for p in sorted(self.outcome.partners)
                         if self.engine.items[p].group == self.engine.items[index].group)
            return Status.FOLDED, f"same source chain as {self.label(party)}, which is in conflict; not counted"
        if index in self.outcome.in_effect and index not in self.outcome.current:
            return Status.PERSISTING, f"kept until {_LATER_HOSTILE_BURN} is judged; re-observe"
        if self.engine.items[index].has_reading and index not in self.outcome.in_effect:
            return self.unapplied(index)
        return self.coverage_status(index)

    def coverage_status(self, index: int) -> tuple[Status, str]:
        if index in self.counted:
            return Status.COUNTED, ""
        best = self.outcome.bests[self.engine.items[index].group]
        return Status.FOLDED, f"same source chain as {self.label(best)}; not counted again"

    def unapplied(self, index: int) -> tuple[Status, str]:
        item = self.engine.items[index]
        q = self.engine.q(index, self.engine.now)
        if item.impaired_status and not self.engine.corroborated:
            return Status.UNCORROBORATED, "not corroborated: " + "; ".join(self.uncorroborated())
        leader = self.leaders.get(item.group, index)
        if leader != index:
            return Status.FOLDED, f"same source chain as {self.label(leader)}; not counted again"
        if index in self.outcome.judged:
            later = f"; {_LATER_HOSTILE_BURN} has been judged" if item.floor_to is not None else ""
            return Status.DECAYED, f"earned when judged; decayed to q {q:.2f}{later}"
        reasons = []
        if q < _READING_Q:
            reasons.append(f"q {q:.2f} below {_READING_Q}")
        if self.vouching[item.dimension] < EARNED:
            reasons.append(f"{item.dimension.value} not earned")
        return Status.BELOW_THRESHOLD, "; ".join(reasons)

    def uncorroborated(self) -> list[str]:
        situation = self.engine.situation
        reasons = []
        if self.engine.burns:
            reasons.append("a confirmed burn is held")
        if situation.custody is not Custody.HELD:
            reasons.append(f"custody is {situation.custody.value}")
        if not situation.sees_routine_station_keeping:
            reasons.append("the detection floor cannot see routine station keeping")
        return reasons


_LATER_HOSTILE_BURN = "a later unusual or unprecedented burn"


def _support(item: EvidenceItem) -> Support:
    return Support(label=item.label, basis=item.basis, controlled=item.controlled)


def _strongest(engine: _Engine, indices: list[int], band_of: Callable[[int], int],
               pick: Callable[[Iterable[int]], int]) -> Support | None:
    """The reading a bound stands on: among those setting it, the strongest basis, then a controlled source."""
    if not indices:
        return None
    band = pick(band_of(i) for i in indices)
    tied = [i for i in indices if band_of(i) == band]
    return _support(engine.items[max(tied, key=lambda i: (_BASIS_RANK[engine.items[i].basis],
                                                           engine.items[i].controlled))])


def _supports(engine: _Engine, outcome: _Outcome) -> tuple[Support | None, Support, tuple[Support, ...]]:
    """What the floor and the ceiling rest on now, and the ceiling readings that have lapsed since judged."""
    floors = sorted(i for i in outcome.in_effect if engine.items[i].floor_to is not None)
    ceilings = sorted(i for i in outcome.in_effect if engine.items[i].ceiling_to is not None)
    lapsed = sorted(i for i in outcome.judged - outcome.in_effect if engine.items[i].ceiling_to is not None)
    floor = _strongest(engine, floors, lambda i: _band_key(engine.items[i].floor_to), max)
    ceiling = _strongest(engine, ceilings, lambda i: int(engine.ceiling_of(i)), min)
    return floor, ceiling or _ACCESS_SUPPORT, tuple(_support(engine.items[i]) for i in lapsed)


def threat_range(items: Iterable[EvidenceItem], situation: Situation) -> ThreatRange:
    """The threat range the evidence has earned, bounded by ACCESS, with its ledger."""
    engine = _Engine(tuple(sorted(items, key=_canonical)), situation)
    outcome = _evaluate(engine)
    floor, ceiling = _bounds(engine, outcome)
    floor_support, ceiling_support, lapsed = _supports(engine, outcome)
    rows = _Ledger(engine, outcome).rows()
    labels = [i.label for i in engine.items]
    return ThreatRange(
        floor=floor,
        ceiling=ceiling,
        coverage=engine.coverage(outcome.rest),
        ledger=rows,
        conflicts=tuple((labels[f], labels[c]) for f, c in outcome.pairs),
        possible_deception=tuple(labels[i] for i in sorted(engine.voided)),
        reobserve=tuple(r.item.label for r in rows if r.status is Status.PERSISTING),
        floor_support=floor_support,
        ceiling_support=ceiling_support,
        lapsed_ceilings=lapsed,
    )


# Section 6.1 and 6.2: the categories and caps, by the names the statement uses.
_INFORMATION_BASE = "information base"
_RIGOUR = "analytical rigour"
_VOLATILITY = "volatility"
_DATA_MODE = "data mode"
_MANUAL = "manual element set"
# Information base HIGH needs at least this many independent source chains. Tuned, not sourced.
_MIN_SOURCE_CHAINS: int = 2
# Information base MODERATE needs at least this many dimensions earned. Tuned, not sourced.
_MIN_EARNED_FOR_MODERATE: int = 2
# Admiralty letters that count as a well-graded source for information base HIGH. Tuned, not sourced.
_WELL_GRADED = frozenset({"A", "B"})
# A burn not judged ROUTINE settles once the orbit after it has been held for this many
# element-set limits: 9 days at GEO. Tuned, not sourced.
_SETTLE_ELSET_LIMITS: float = 3.0
_REMOVED = frozenset({Status.VOIDED, Status.CONFLICT})
# Element sets in these modes describe an exercise, not the satellite.
_EXERCISE_MODES = frozenset({"SYNTHETIC", "TEST", "EXERCISE", "SIMULATED"})
_REAL_MODE = "REAL"
_MANUAL_MODE = "MANUAL"
# A manual element set caps Understanding at the operator's stated confidence;
# an unstated or unknown one reads as UNCONFIRMED. Tuned, not sourced.
_MANUAL_CAP: dict[str, Understanding] = {
    "CONFIRMED": Understanding.HIGH, "HIGH": Understanding.HIGH, "MEDIUM": Understanding.MODERATE,
    "LOW": Understanding.LOW, "UNCONFIRMED": Understanding.LOW,
}

_Finding = tuple[str, Understanding, str]


def _computed_capability_reading(result: ThreatRange) -> bool:
    return any(r.applied and r.item.dimension is Dimension.CAPABILITY and r.item.basis is Basis.COMPUTED
               for r in result.ledger)


def _information_base(result: ThreatRange) -> tuple[Understanding, str]:
    """HIGH: Identity (or Interactions), Capability and Behaviour earned, 2 chains, an A or B in C or B."""
    earned = {d for d, u in result.coverage.items() if depth(u) is Depth.EARNED}
    # A chain, or a grade, stands only on an item that covers its dimension at least
    # partially now: a rejected detection or a long-decayed figure is held, not founded on.
    held = [r for r in result.ledger if r.status not in _REMOVED and r.q >= PARTIAL]
    chains = {r.item.group[1] for r in held}
    graded = any(r.item.dimension in _RESET_DIMENSIONS and r.item.source_grade in _WELL_GRADED for r in held)
    needs = [Dimension.CAPABILITY, Dimension.BEHAVIOUR]
    if not earned & {Dimension.IDENTITY, Dimension.INTERACTIONS}:
        needs.insert(0, Dimension.IDENTITY)
    missing = [f"{d.value} {depth(result.coverage[d]).value}" for d in needs if d not in earned]
    if not missing:
        missing = [*(["one source chain only"] if len(chains) < _MIN_SOURCE_CHAINS else []),
                   *([] if graded else ["no source graded A or B in Capability or Behaviour"])]
    if not missing:
        return Understanding.HIGH, ""
    founded = Dimension.BEHAVIOUR in earned or (
        Dimension.CAPABILITY in earned and _computed_capability_reading(result))
    level = Understanding.MODERATE if len(earned) >= _MIN_EARNED_FOR_MODERATE and founded else Understanding.LOW
    return level, ", ".join(missing)


def _grade(floor: Support | None, ceiling: Support, *, lapsed: bool = False) -> tuple[Understanding, str]:
    """Rigour for one pair of bounds: the weakest basis governs, and HIGH needs a controlled source."""
    bounds = [(name, s) for name, s in (("floor", floor), ("ceiling", ceiling)) if s is not None]
    least = weakest(*(s.basis for _, s in bounds))
    name, support = next((n, s) for n, s in bounds if s.basis is least)
    past = lapsed and name == "ceiling"
    rests, since = ("rested", ", since decayed") if past else ("rests", "")
    if least is Basis.LOOKUP:
        return Understanding.LOW, f"the {name} {rests} on a lookup ({support.label}){since}"
    if least is Basis.SAMPLED:
        return Understanding.MODERATE, f"the {name} {rests} on a sampled figure ({support.label}){since}"
    if any(s.controlled for _, s in bounds):
        return Understanding.HIGH, ""
    return Understanding.MODERATE, "computed from uncontrolled sources only"


def _rigour(result: ThreatRange) -> tuple[Understanding, str]:
    """HIGH: the bounds rest on COMPUTED readings, a controlled source among them; LOW on any lookup.

    Judged on what sets each bound now, so a superseded or decayed reading
    lends the range nothing. A ceiling reading that has lapsed is still
    counted as though it set the ceiling: it may lower rigour, never raise
    it, so ageing alone cannot raise Understanding (I4).
    """
    grades = [_grade(result.floor_support, result.ceiling_support),
              *(_grade(result.floor_support, lapsed, lapsed=True) for lapsed in result.lapsed_ceilings)]
    return min(grades, key=lambda graded: graded[0])


def _unsettled_burn(situation: Situation) -> str:
    """The latest burn, when it is not ROUTINE and the orbit after it is not yet held long enough."""
    held = [b for b in situation.burns if b.epoch <= situation.now]
    if not held:
        return ""
    latest = max(held, key=lambda b: (b.epoch, b.normality in _HOSTILE))
    settle = timedelta(hours=_SETTLE_ELSET_LIMITS * situation.elset_limit_hours)
    newest = situation.newest_elset_at
    if latest.normality is Normality.ROUTINE or (newest is not None and newest - latest.epoch >= settle):
        return ""
    age = age_text((situation.now - latest.epoch).total_seconds() / 3600.0)
    if latest.normality is Normality.NOT_ENOUGH_HISTORY:
        return f"a burn {age} ago, too little history to judge it, whose new orbit is not yet settled"
    return f"an {latest.normality.value} burn {age} ago whose new orbit is not yet settled"


def _volatility(result: ThreatRange, situation: Situation) -> tuple[Understanding, str]:
    """HIGH: custody held, no conflict, the latest burn ROUTINE or settled; LOW: custody lost."""
    if situation.custody is Custody.LOST:
        return Understanding.LOW, "custody lost"
    parts = [
        *(["custody degraded"] if situation.custody is Custody.DEGRADED else []),
        *(f"conflicting evidence, {f} against {c}" for f, c in result.conflicts),
        *(f"possible deception, {label}" for label in result.possible_deception),
        *([burn] if (burn := _unsettled_burn(situation)) else []),
        *(["a truncated history"] if situation.history_truncated else []),
    ]
    return (Understanding.MODERATE, " and ".join(parts)) if parts else (Understanding.HIGH, "")


def _caps(situation: Situation) -> list[_Finding]:
    """Section 6.2: an exercise mode caps at LOW, an unrecorded one at MODERATE, a manual set at its confidence."""
    mode = (situation.data_mode or "").strip().upper()
    if mode == _REAL_MODE:
        return []
    if mode in _EXERCISE_MODES:
        return [(_DATA_MODE, Understanding.LOW,
                 f"computed from {mode} element sets: describes the exercise, not the satellite")]
    if mode == _MANUAL_MODE:
        stated = (situation.manual_confidence or "").strip().upper()
        level = _MANUAL_CAP.get(stated, Understanding.LOW)
        why = f"entered at the operator's stated confidence, {stated.lower() or 'unstated'}"
        return [] if level is Understanding.HIGH else [(_MANUAL, level, why)]
    return [(_DATA_MODE, Understanding.MODERATE, "the data mode is not recorded")]


def _statement(level: Understanding, findings: list[_Finding]) -> str:
    """The AnCR form: the level, then the governing categories and what each is missing."""
    if level is Understanding.HIGH:
        return "Understanding HIGH. Information base, analytical rigour and volatility all meet their criteria."
    governing = "; ".join(f"{name}, {why}" for name, found, why in findings if found == level)
    return f"Understanding {level.name}. Governing: {governing}."


def understand(result: ThreatRange, situation: Situation) -> UnderstandingRating:
    """How well founded *result* is: the weakest of the three categories and the caps."""
    information, information_why = _information_base(result)
    rigour, rigour_why = _rigour(result)
    volatility, volatility_why = _volatility(result, situation)
    findings: list[_Finding] = [
        (_INFORMATION_BASE, information, information_why), (_RIGOUR, rigour, rigour_why),
        (_VOLATILITY, volatility, volatility_why), *_caps(situation),
    ]
    level = min(found for _, found, _ in findings)
    return UnderstandingRating(
        level=level,
        information_base=information,
        rigour=rigour,
        volatility=volatility,
        governing=tuple(name for name, found, _ in findings if found == level < Understanding.HIGH),
        reasons=tuple((name, why) for name, found, why in findings if found < Understanding.HIGH),
        statement=_statement(level, findings),
    )


@dataclass(frozen=True)
class ThreatUnderstanding:
    """Threat as a range, Understanding as a rating, and the verdict they give.

    *cues* are what to collect next, most steps of range per hour first
    (SPC-170); empty unless they were asked for.
    """

    range: ThreatRange
    understanding: UnderstandingRating
    verdict: Verdict
    cues: tuple[Cue, ...] = ()


def assess(items: Iterable[EvidenceItem], situation: Situation, *, with_cues: bool = False) -> ThreatUnderstanding:
    """The threat range the evidence earns, how well founded it is, and the verdict; the cues on request."""
    held = tuple(items)
    result = threat_range(held, situation)
    rating = understand(result, situation)
    legacy = situation.access if situation.legacy is None else situation.legacy
    return ThreatUnderstanding(range=result, understanding=rating,
                               verdict=verdict_for(legacy, result.floor, result.ceiling, rating.level),
                               cues=cues(held, situation) if with_cues else ())


# ── Adapters: what SPECTRE holds, as evidence items (SPC-165) ─────────────────
#
# Each adapter reads one held signal and builds the items of sections 5.1 to
# 5.3 of the concept. What an item may claim is refused by EvidenceItem
# itself, so an adapter cannot build a reading the model forbids.

#: The names the 18 SDS catalogue arrives under (provider keys: upper case,
#: letters and digits only). Each is a copy of one catalogue, so they are one
#: source chain and count once (section 2.4 and 5.3).
_18SDS = "18SDS"
_18SDS_ALIASES = frozenset({_18SDS, "18SPCS", "18THSPCS", "SPACETRACK", "JSPOC", "CSPOC"})
#: Provider grades, the Admiralty letter, by provider key. The 18 SDS catalogue
#: through UDL is B; a provider not listed, commercial or unattributed, reads
#: C. An own or allied sensor is A once an analyst lists it. The table is data
#: the owner may move under UK sovereign handling (concept section 9, decision
#: 5). Tuned, not sourced.
PROVIDER_GRADES: dict[str, str] = dict.fromkeys(sorted(_18SDS_ALIASES), "B")
_UNLISTED_PROVIDER_GRADE = "C"
#: The key an element set with no recorded source is grouped under, as Pattern of Life groups it.
UNATTRIBUTED = "UNATTRIBUTED"
#: Grades whose provider is own, allied or the 18 SDS: a controlled source (section 6.1, rigour).
_CONTROLLED_GRADES = frozenset({"A", "B"})
# A provider's own fit, not yet confirmed by another: Admiralty 2. A provider that
# corroborated a burn confirms it: Admiralty 1. Tuned, not sourced.
_PROVIDER_CREDIBILITY = 2
_CORROBORATION_CREDIBILITY = 1
# An open-source intel record is C; 3 when it is undated and names one source,
# else 2. Tuned, not sourced.
_INTEL_GRADE = "C"
_INTEL_CREDIBILITY = 2
_INTEL_CREDIBILITY_THIN = 3
#: Separators that mark a record naming more than one source.
_SOURCE_SEPARATORS = ("/", ";", " and ")
#: The record field an analyst dates a record with, ISO 8601. None of the 44
#: bundled records carries one yet.
RECORD_DATE_FIELD = "assessed_at"
# A status is declared by the object's operator: D, and 3. Tuned, not sourced.
_STATUS_GRADE = "D"
_STATUS_CREDIBILITY = 3
# GCAT, a curated public catalogue, read directly: B2. Tuned, not sourced.
_GCAT_GRADE = "B"
_GCAT_CREDIBILITY = 2
#: The GCAT fields named in the ledger, and how each is introduced.
_GCAT_FIELDS: tuple[tuple[str, str], ...] = (("Bus", "bus"), ("LDate", "launched"), ("Owner", "owner"))
#: A GCAT cell that holds nothing.
_GCAT_EMPTY = frozenset({"", "-"})
# "No burns" is coverage only, read at half extraction and capped as a ROUTINE
# verdict is, because a quiet object and a careful one look the same. It
# counts only over a held span of at least 30 days. Tuned, not sourced.
_ABSENCE_EXTRACTION = 0.5
_ABSENCE_MIN_SPAN_DAYS = 30.0
# A gap between held element sets longer than this could hide a burn: the
# long-gap limit Pattern of Life flags a burn with. Tuned, not sourced.
_ABSENCE_LONG_GAP_DAYS = 10.0
#: The anomaly index is an uncalibrated heuristic: read as an assumed figure.
_ANOMALY_EXTRACTION = ASSUMED_FIGURE_EXTRACTION
# A discretionary reserve below this share of its maximum lowers the ceiling
# to MEDIUM, the cut threat_assessment grades capability by. Tuned, not sourced.
_RESERVE_SHARE_FOR_MEDIUM = 0.5
#: A detection grade the forensic budget never reached is read as LOW.
_UNASSESSED_DETECTION = "LOW"
#: A burn too soon to judge is listed as missing (section 5.3): no normality
#: verdict was extracted, so it carries no weight and earns nothing.
_UNJUDGED_EXTRACTION = 0.0
_HOSTILE_FLOOR: dict[Normality, Band] = {Normality.UNPRECEDENTED: Band.HIGH, Normality.UNUSUAL: Band.MEDIUM}
_AGGRESSIVE_POSTURES = frozenset({Posture.AGGRESSIVE, Posture.BEYOND_PLATFORM})
_POSTURE_FLOOR: Band = Band.MEDIUM
_DAY = timedelta(days=1)
#: A manoeuvre-attributable warning change against one of ours reads floor HIGH (section 4.6).
_APPROACH_FLOOR: Band = Band.HIGH
#: The root an approach's items arrive under, with the object after it.
_APPROACH_ROOT = "approach:"
_APPROACH_OURS = "one of yours: a confirmed burn within 7 days brought it in reach sooner"
_APPROACH_NOT_OURS = "not one of yours: coverage only"
_APPROACH_ROUTINE = "one of yours, but every burn it rests on was judged routine: coverage only"


@dataclass(frozen=True)
class BurnSignal:
    """One confirmed burn in a held history, as the adapters read it."""

    epoch: datetime
    normality: Normality
    detection: str = _UNASSESSED_DETECTION   # astro/dv_estimation grade
    source: str = UNATTRIBUTED               # the provider whose fits detected it
    corroborated_by: tuple[str, ...] = ()    # other providers that reported it
    long_gap: bool = False
    posture: Posture | None = None


@dataclass(frozen=True)
class HistorySignals:
    """What one element-set history says about the object, read once.

    *provider* is the provider most of its sets came from, the chain every
    figure derived from the whole history counts under. *tank_spent* is
    whether the tank reads spent on the regime's assumptions, and
    *burn_after_spent* whether a confirmed burn followed the moment it first
    did. *long_gap_open* is a gap between held sets long enough to hide a burn.
    """

    provider: str
    newest_at: datetime
    span_days: float
    burns: tuple[BurnSignal, ...] = ()
    reserve_remaining_m_s: float | None = None
    reserve_max_m_s: float | None = None
    tank_spent: bool = False
    burn_after_spent: bool = False
    anomaly_score: float | None = None
    detection_floor_m_s: float | None = None
    sees_routine_station_keeping: bool = False
    long_gap_open: bool = False
    truncated: bool = False


def _provider_lookup_key(provider: str) -> str:
    return "".join(ch for ch in provider.upper() if ch.isalnum()) or UNATTRIBUTED


def provider_grade(provider: str, grades: Mapping[str, str] = PROVIDER_GRADES) -> str:
    """The Admiralty letter for an element-set provider; one not listed reads C."""
    return grades.get(_provider_lookup_key(provider), _UNLISTED_PROVIDER_GRADE)


def _source_key(source: object) -> str:
    """A provider as Pattern of Life names it, upper case: how the ledger shows it."""
    return str(source or "").strip().upper() or UNATTRIBUTED


def source_chain(provider: object) -> str:
    """The source chain a provider's element sets belong to: the group key, with copies of one catalogue as one.

    Spellings of one provider ("LEO LABS", "LeoLabs") are one chain, and
    every name the 18 SDS catalogue arrives under is that catalogue.
    """
    key = _provider_lookup_key(str(provider or ""))
    return _18SDS if key in _18SDS_ALIASES else key


def record_date(record: Mapping[str, Any] | None) -> datetime | None:
    """The date an analyst gave a record, in UTC, or None when it carries none that can be read."""
    raw = (record or {}).get(RECORD_DATE_FIELD)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _identity_note(dated: datetime | None, source: str, single: bool, level: str, band: Band | None) -> str:
    """What the record is, as section 7.3 lists it ("undated, single open source"), and any unread level."""
    sourced = ("single open source" if single else "") if source else "unsourced"
    record = ", ".join(word for word in ("" if dated else "undated", sourced) if word)
    unread = f"its threat level '{level}' is not a recognised band, so it carries no reading" if (
        level and band is None) else ""
    return "; ".join(part for part in (record, unread) if part)


def _declared_status(record: Mapping[str, Any], satno: str, dated: datetime | None) -> tuple[EvidenceItem, ...]:
    """The recorded status: the operator's own declaration, an impaired status the model can void."""
    status = str(record.get("status") or "").strip()
    if not status:
        return ()
    impaired = CapabilityEvidence(operational_status=status).is_impaired()
    return (EvidenceItem(
        dimension=Dimension.CAPABILITY, label=f"recorded status {status}", derived_from=f"status:{satno}",
        source_grade=_STATUS_GRADE, credibility=_STATUS_CREDIBILITY, extraction=ASSESSED_LABEL_EXTRACTION,
        basis=Basis.LOOKUP, observed_at=dated, manufacturable=True, impaired_status=impaired,
        ceiling_to=_IMPAIRED_CEILING_FLOOR if impaired else None, note="declared, not observed",
    ),)


def intel_items(record: Mapping[str, Any] | None, satno: str) -> tuple[EvidenceItem, ...]:
    """The intel record: Identity, a prior, and its recorded status as declared Capability evidence.

    The assessed role raises the floor to MEDIUM, and no higher, only when
    the record is dated and sourced (section 4.6). The status is the object
    operator's own declaration: coverage only, unless it says the object
    cannot manoeuvre, when it is an impaired status the model voids against a
    newer burn and lets lower the ceiling no further than MEDIUM.
    """
    if not record:
        return ()
    dated = record_date(record)
    source = str(record.get("source") or "").strip()
    single = not any(sep in source for sep in _SOURCE_SEPARATORS)
    level = str(record.get("threat_level") or "").strip()
    band = CapabilityEvidence(intel_threat_level=level).recognised_threat_level()
    role = str(record.get("assessed_threat") or "").strip()
    prior = band is not None and band >= Band.HIGH and dated is not None and bool(source)
    identity = EvidenceItem(
        dimension=Dimension.IDENTITY, label=f"intel record, role {role}" if role else "intel record",
        derived_from=f"intel-record:{satno}", source_grade=_INTEL_GRADE,
        credibility=_INTEL_CREDIBILITY_THIN if dated is None and single else _INTEL_CREDIBILITY,
        extraction=ASSESSED_LABEL_EXTRACTION, basis=Basis.LOOKUP, observed_at=dated,
        floor_to=_PRIOR_FLOOR_CAP if prior else None, note=_identity_note(dated, source, single, level, band),
    )
    return (identity, *_declared_status(record, satno, dated))


def gcat_items(fields: Mapping[str, str] | None, fetched_at: datetime | None, satno: str) -> tuple[EvidenceItem, ...]:
    """The GCAT catalogue entry: Identity coverage only, dated from the cache's refresh."""
    if fields is None:
        return ()
    named = [f"{word} {value}" for key, word in _GCAT_FIELDS
             if (value := str(fields.get(key) or "").strip()) not in _GCAT_EMPTY]
    return (EvidenceItem(
        dimension=Dimension.IDENTITY, label="GCAT entry: " + ", ".join(named) if named else "GCAT entry",
        derived_from=f"gcat:{satno}", source_grade=_GCAT_GRADE, credibility=_GCAT_CREDIBILITY,
        extraction=CATALOGUE_FIELD_EXTRACTION, basis=Basis.LOOKUP, observed_at=fetched_at,
        note="declared fields: recorded, never move a band",
    ),)


def _history_item(signals: HistorySignals, grades: Mapping[str, str], **kw: Any) -> EvidenceItem:
    """An item derived from the whole history: its provider's chain, dated from the newest set."""
    grade = provider_grade(signals.provider, grades)
    args: dict[str, Any] = {
        "derived_from": f"elset-history:{source_chain(signals.provider)}", "source_grade": grade,
        "credibility": _PROVIDER_CREDIBILITY, "basis": Basis.COMPUTED, "observed_at": signals.newest_at,
        "controlled": grade in _CONTROLLED_GRADES,
    }
    args.update(kw)
    return EvidenceItem(**args)


def _reserve_item(signals: HistorySignals, grades: Mapping[str, str]) -> tuple[EvidenceItem, ...]:
    """Section 5.2: the discretionary reserve. Ceiling MINIMAL when spent with no later burn."""
    remaining, maximum = signals.reserve_remaining_m_s, signals.reserve_max_m_s
    if remaining is None or maximum is None:
        return ()
    figure = f"reserve {remaining:.0f} of {maximum:.0f} m/s"
    ceiling: Band | None = None
    note = "on the regime's assumed specific impulse and propellant fraction"
    if signals.tank_spent and signals.burn_after_spent:
        note = "a confirmed burn followed the moment the tank read spent, so the tank model does not hold"
    elif signals.tank_spent:
        ceiling, figure = Band.MINIMAL, f"tank spent: {figure}"
    elif maximum > 0.0 and remaining / maximum < _RESERVE_SHARE_FOR_MEDIUM:
        ceiling = Band.MEDIUM
    return (_history_item(signals, grades, dimension=Dimension.CAPABILITY, label=figure,
                          extraction=ASSUMED_FIGURE_EXTRACTION, ceiling_to=ceiling, note=note),)


def _grade_of(detection: str) -> str:
    return detection if detection in DETECTION_EXTRACTION else _UNASSESSED_DETECTION


def _detection(burn: BurnSignal) -> str:
    return _grade_of(burn.detection)


def _seen_by(burn: BurnSignal, provider: str, credibility: int, grades: Mapping[str, str], **kw: Any) -> EvidenceItem:
    """The latest burn as one provider reported it. One too soon to judge is listed and weighs nothing."""
    grade = provider_grade(provider, grades)
    unjudged = burn.normality is Normality.NOT_ENOUGH_HISTORY
    args: dict[str, Any] = {
        "dimension": Dimension.BEHAVIOUR, "label": f"latest burn, {burn.normality.value}",
        "derived_from": f"elset-history:{source_chain(provider)}", "source_grade": grade, "credibility": credibility,
        "extraction": _UNJUDGED_EXTRACTION if unjudged else burn_extraction(_detection(burn), long_gap=burn.long_gap),
        "basis": Basis.COMPUTED, "observed_at": burn.epoch, "floor_to": _HOSTILE_FLOOR.get(burn.normality),
        "routine": burn.normality is Normality.ROUTINE, "controlled": grade in _CONTROLLED_GRADES,
        "note": "too little history to judge whether it is normal: listed as missing" if unjudged else "",
    }
    args.update(kw)
    return EvidenceItem(**args)


def _burn_items(burn: BurnSignal, grades: Mapping[str, str]) -> tuple[EvidenceItem, ...]:
    """Section 5.3: the latest burn, once per source chain that reported it, and its posture.

    Each provider in ``corroborated_by`` opens its own group at credibility 1
    (section 4.5). A copy of the detecting provider's own report does not,
    and nor does another copy of one catalogue: the 18 SDS catalogue counts
    once under whichever name it arrives (section 5.3).
    """
    own = source_chain(burn.source)
    named: dict[str, str] = {}
    for provider in sorted(_source_key(p) for p in burn.corroborated_by):
        named.setdefault(source_chain(provider), provider)
    named.pop(own, None)
    items = [_seen_by(burn, own, _PROVIDER_CREDIBILITY, grades)]
    items.extend(_seen_by(burn, chain, _CORROBORATION_CREDIBILITY, grades,
                          label=f"latest burn, {burn.normality.value}, corroborated by {name}")
                 for chain, name in sorted(named.items()))
    if burn.posture in _AGGRESSIVE_POSTURES:
        items.append(_seen_by(burn, own, _PROVIDER_CREDIBILITY, grades, floor_to=_POSTURE_FLOOR, routine=False,
                              extraction=burn_extraction(_detection(burn), long_gap=burn.long_gap),
                              label=f"latest burn posture {burn.posture.value.lower()}", note=""))
    return tuple(items)


def _anomaly_item(signals: HistorySignals, grades: Mapping[str, str]) -> tuple[EvidenceItem, ...]:
    """The anomaly index: a lookup, its rung a floor capped at MEDIUM because it is uncalibrated."""
    if signals.anomaly_score is None:
        return ()
    rung = min(Band[anomaly_risk_level(signals.anomaly_score)], _PRIOR_FLOOR_CAP)
    return (_history_item(signals, grades, dimension=Dimension.BEHAVIOUR,
                          label=f"anomaly index {signals.anomaly_score:.0f}", extraction=_ANOMALY_EXTRACTION,
                          basis=Basis.LOOKUP, floor_to=rung if rung > Band.MINIMAL else None,
                          note="an uncalibrated heuristic index"),)


def _absence_holds(signals: HistorySignals, access_delta_v_m_s: float, custody: Custody) -> bool:
    """Section 5.3: custody held, 30 days held, a floor below the intercept's cost, no gap open."""
    floor = signals.detection_floor_m_s
    return (custody is Custody.HELD and signals.span_days >= _ABSENCE_MIN_SPAN_DAYS
            and floor is not None and floor < access_delta_v_m_s and not signals.long_gap_open)


def history_items(signals: HistorySignals, *, access_delta_v_m_s: float, custody: Custody,
                  grades: Mapping[str, str] = PROVIDER_GRADES) -> tuple[EvidenceItem, ...]:
    """The element-set history: its reserve, its latest burn, its anomaly index or its silence.

    *access_delta_v_m_s* is what the intercept costs: "no burns" counts only
    when the detection floor could have seen a burn that size.
    """
    items = [*_reserve_item(signals, grades), *_anomaly_item(signals, grades)]
    if signals.burns:
        items.extend(_burn_items(max(signals.burns, key=lambda b: b.epoch), grades))
    elif _absence_holds(signals, access_delta_v_m_s, custody):
        items.append(_history_item(
            signals, grades, dimension=Dimension.BEHAVIOUR, label=f"no burns in {signals.span_days:.0f} days",
            extraction=_ABSENCE_EXTRACTION, routine=True, note="an absence: adds coverage and moves no band"))
    return tuple(items)


def _approach_label(edge: Edge, hours: Callable[[float], str]) -> str:
    """The approach in the operator's words; a cut states its size, since a rounded pair can read the same."""
    after = edge.after_h or 0.0
    if edge.change is Change.NEWLY_IN_REACH:
        return f"{edge.target} put in reach by its burn, {hours(after)} warning"
    before = edge.before_h or 0.0
    return f"warning on {edge.target} cut {hours(before - after)} by its burn, {hours(before)} to {hours(after)}"


def _approach_note(edge: Edge, routine: bool) -> str:
    if not edge.ours:
        return _APPROACH_NOT_OURS
    return _APPROACH_ROUTINE if routine else _APPROACH_OURS


def _approach_item(edge: Edge, grades: Mapping[str, str], judged: Mapping[datetime, Normality],
                   hours: Callable[[float], str]) -> EvidenceItem:
    """One approach, as reliable as the weakest burn it rests on: its provider's grade and its detection.

    Every approach one burn explains derives from that one detection, so its
    items share one source chain and count once (section 2.4): the group is
    the object and the provider, not the pair. One resting only on burns
    judged ROUTINE is coverage only (I9); a routine burn beside a hostile
    one lowers nothing, as ROUTINE never does.
    """
    provider = min((b.provider for b in edge.burns),
                   key=lambda p: (SOURCE_RELIABILITY[provider_grade(p, grades)], source_chain(p)))
    grade = provider_grade(provider, grades)
    routine = all(judged.get(b.epoch) is Normality.ROUTINE for b in edge.burns)
    return EvidenceItem(
        dimension=Dimension.INTERACTIONS, label=_approach_label(edge, hours),
        derived_from=f"{_APPROACH_ROOT}{edge.actor}:{source_chain(provider)}", source_grade=grade,
        credibility=_PROVIDER_CREDIBILITY,
        extraction=min(burn_extraction(_grade_of(b.detection), long_gap=b.long_gap) for b in edge.burns),
        basis=Basis.COMPUTED, observed_at=edge.burn_at,
        floor_to=_APPROACH_FLOOR if edge.ours and not routine else None,
        controlled=grade in _CONTROLLED_GRADES, routine=routine, note=_approach_note(edge, routine),
    )


def interaction_items(edges: Iterable[Edge], grades: Mapping[str, str] = PROVIDER_GRADES, *,
                      judged: Iterable[HeldBurn] = (),
                      hours: Callable[[float], str] = age_text) -> tuple[EvidenceItem, ...]:
    """Section 5.4: each manoeuvre-attributable approach (``domain/interaction_graph.py``) as Interactions evidence.

    One that brought one of ours in reach, or in reach sooner, reads floor
    HIGH; one to any other target is coverage only. Either is a reading only
    once Interactions is earned, as any reading is (section 4.6). *judged*
    are the held history's burns with their normality verdicts: an approach
    resting only on ROUTINE burns moves no band (I9). *hours* writes a
    warning; a panel passes the format its warning section uses.
    """
    verdicts = {b.epoch: b.normality for b in judged}
    return tuple(_approach_item(edge, grades, verdicts, hours) for edge in edges)


def window_custody(signals: HistorySignals, now: datetime, elset_limit_hours: float) -> Custody:
    """Section 5.3: whether custody was held across the history's own window, judged on its own sets.

    The absence rule asks this of the history, not of whichever element set a
    panel is looking at, so one object reads one strip on every panel. Held
    while the newest set is within the regime's limit, degraded when UDL's
    record cap cut the history short, and lost past the limit.
    """
    if now - signals.newest_at > timedelta(hours=elset_limit_hours):
        return Custody.LOST
    return Custody.DEGRADED if signals.truncated else Custody.HELD


def with_record(situation: Situation, record: Mapping[str, Any] | None) -> Situation:
    """*situation* with the floor its intel record would set once dated and sourced, for the record's cue."""
    level = str((record or {}).get("threat_level") or "").strip()
    band = CapabilityEvidence(intel_threat_level=level).recognised_threat_level()
    return replace(situation, record_prior=_PRIOR_FLOOR_CAP if band is not None and band >= Band.HIGH else None)


def with_history(situation: Situation, signals: HistorySignals | None) -> Situation:
    """*situation* with what the history says: its burns, newest set, detection floor and truncation."""
    if signals is None:
        return situation
    return replace(
        situation,
        burns=tuple(HeldBurn(b.epoch, b.normality) for b in signals.burns),
        newest_elset_at=signals.newest_at,
        sees_routine_station_keeping=signals.sees_routine_station_keeping,
        history_truncated=signals.truncated,
    )


def _spent(total_m_s: float, discretionary_m_s: float, propellant: Any) -> bool:
    """The tank reads spent: the discretionary reserve gone, or the load used to the spent line."""
    if discretionary_m_s >= propellant.discretionary_max_m_s:
        return True
    # The spent line and g0 are threat_assessment's and pol_assessment's own, so the walk cannot drift from them.
    exhaust = propellant.assumed_isp_s * STANDARD_GRAVITY_M_S2
    used_pct = (1.0 - math.exp(-total_m_s / exhaust)) / propellant.propellant_fraction * 100.0
    return bool(used_pct >= PROPELLANT_SPENT_PCT)


def _tank(views: list[Any], propellant: Any) -> tuple[bool, bool]:
    """Whether the tank reads spent, and whether a confirmed burn followed the moment it first did.

    Walks the confirmed burns since any reserve reset, oldest first, as
    Pattern of Life counts them.
    """
    reset = propellant.reserve_reset
    ordered = sorted(views, key=lambda v: v.manoeuvre.epoch)
    total = discretionary = 0.0
    for index, view in enumerate(ordered):
        if reset is not None and view.manoeuvre.epoch < reset:
            continue
        total += view.delta_v_m_s
        discretionary += 0.0 if view.is_routine else view.delta_v_m_s
        if _spent(total, discretionary, propellant):
            return True, index < len(ordered) - 1
    return False, False


def _long_gap_open(pol: Any, epochs: list[datetime]) -> bool:
    gaps = (later - earlier for earlier, later in zip(epochs, epochs[1:], strict=False))
    return bool(pol.skipped_long_gap > 0) or any(gap > _ABSENCE_LONG_GAP_DAYS * _DAY for gap in gaps)


def _burn_signals(views: list[Any], start: datetime) -> tuple[BurnSignal, ...]:
    """Each confirmed burn, judged against those before it, oldest first."""
    burns = burns_from_views(views)
    signals = [
        BurnSignal(
            epoch=burn.epoch, normality=judge_burn(burn, burns, start).verdict,
            detection=str(view.manoeuvre.confidence), source=source_chain(view.manoeuvre.tle_after.source),
            corroborated_by=tuple(view.manoeuvre.corroborated_by), long_gap=burn.long_gap,
            posture=view.posture.posture,
        )
        for view, burn in zip(views, burns, strict=True)
    ]
    return tuple(sorted(signals, key=lambda b: b.epoch))


def history_signals(pol: Any, assessment: Any) -> HistorySignals:
    """Read a held history (Pattern of Life's ``PolAnalysis``) and its ``PolAssessment`` once."""
    epochs = sorted(r.epoch for r in pol.records)
    counts = Counter(source_chain(r.source) for r in pol.records)
    provider = min(counts, key=lambda key: (-counts[key], key))
    views = list(assessment.manoeuvres)
    propellant = assessment.propellant
    spent, after = _tank(views, propellant)
    detection = assessment.detection
    return HistorySignals(
        provider=provider, newest_at=epochs[-1], span_days=float(pol.span_days),
        burns=_burn_signals(views, epochs[0]),
        reserve_remaining_m_s=propellant.discretionary_remaining_m_s,
        reserve_max_m_s=propellant.discretionary_max_m_s,
        tank_spent=spent, burn_after_spent=after,
        anomaly_score=assessment.anomaly.overall if assessment.anomaly is not None else None,
        detection_floor_m_s=detection.floor_m_s if detection is not None else None,
        sees_routine_station_keeping=bool(detection is not None and detection.sees_routine_station_keeping),
        long_gap_open=_long_gap_open(pol, epochs),
        truncated=pol.history_truncated_at is not None,
    )


# ── Decide-by (SPC-167, live) ─────────────────────────────────────────────────


def computed_incapacity(result: ThreatUnderstanding) -> LedgerRow | None:
    """The computed reading that would set a MINIMAL Threat ceiling, applied or not; an applied one first.

    A recorded status can never be it: an impaired status lowers the ceiling
    no further than MEDIUM, and it is a lookup besides.
    """
    rows = [row for row in result.range.ledger
            if row.item.ceiling_to is Band.MINIMAL and row.item.basis is Basis.COMPUTED]
    return next((row for row in rows if row.applied), rows[0] if rows else None)


def earned_incapacity(result: ThreatUnderstanding) -> LedgerRow | None:
    """The computed reading that has set a MINIMAL Threat ceiling, while Understanding is not LOW.

    Section 7.4: decide-by is withheld only on this, or when custody is lost.
    A spent tank must be computed, earned by independent histories and still
    in effect; an applied MINIMAL ceiling is the range's ceiling, so the range
    need not be asked again.
    """
    row = computed_incapacity(result)
    if row is None or not row.applied or result.understanding.level is Understanding.LOW:
        return None
    return row


# ── Cues and the value of information (SPC-170) ───────────────────────────────
#
# Section 4.10. For each dimension not yet earned, the range is re-run twice
# with one hypothetical group of the collection's typical grade: once with the
# most benign reading the dimension admits, once with the most hostile. The
# steps of range the collection would remove are
#     (ceiling now - ceiling benign) + (floor hostile - floor now),
# each half no less than nothing, the whole no more than the range has, and
# the cues are ranked by steps per hour to collect. One cue is not tied to an
# unearned dimension: an undated intel record can be dated and sourced by an
# analyst whatever Identity's coverage, as contrast B of section 4.12 ranks it.
# Every cue is worked out and ranked, but only a fed one can deliver what it
# names today: the sweep's warning change is Interactions evidence since
# SPC-172, but nothing turns a UDL conjunction into evidence until SPC-173,
# and the sweep holds one merged history per object (section 9, decision 8),
# so a second provider's history has nowhere to go yet.

#: The roots the held signals arrive under, as the adapters above name them.
_HISTORY_ROOT = "elset-history:"
_RECORD_ROOT = "intel-record:"
_GCAT_ROOT = "gcat:"
_PHOTOMETRY_ROOT = "photometry:"
_NOTSO_ROOT = "notso:"
#: A hypothetical group's root, so it is independent of everything held.
_PROBE_ROOT = "hypothetical:"
# Hours each collection takes. Holding conjunctions and pulling a catalogue
# entry are a lookup inside SPECTRE; a history is one more UDL query; dating
# and sourcing a record needs an analyst. Tuned, not sourced.
_CONJUNCTION_HOURS: float = 0.25
_GCAT_HOURS: float = 0.25
_HISTORY_HOURS: float = 0.5
_RECORD_HOURS: float = 4.0
_MINUTES_PER_HOUR = 60.0
#: The cue when no element-set history is held: the one screening names for an actor without one (section 7.2).
PULL_HISTORY = "pull its element-set history"


@dataclass(frozen=True)
class _Probe:
    """What one collection could show in one dimension: its grade and its most hostile and benign readings."""

    dimension: Dimension
    root: str
    source_grade: str
    credibility: int
    extraction: float
    basis: Basis
    controlled: bool = False
    hostile_floor: Band | None = None
    benign_ceiling: Band | None = None

    def item(self, now: datetime, *, hostile: bool) -> EvidenceItem:
        """The hypothetical group, observed now. A benign burn is a routine one: coverage only."""
        return EvidenceItem(
            dimension=self.dimension, label=f"hypothetical {self.dimension.value}", derived_from=self.root,
            source_grade=self.source_grade, credibility=self.credibility, extraction=self.extraction,
            basis=self.basis, observed_at=now, controlled=self.controlled,
            floor_to=self.hostile_floor if hostile else None, ceiling_to=None if hostile else self.benign_ceiling,
            routine=not hostile and self.dimension is Dimension.BEHAVIOUR,
        )


@dataclass(frozen=True)
class _Collection:
    observation: str
    hours: float
    probes: tuple[_Probe, ...]
    record: bool = False
    fed: bool = True


@dataclass(frozen=True)
class Cue:
    """One observation that would narrow the range: what to collect, what it could do and how long it takes.

    *steps* are the band steps of range it would remove (section 4.10).
    *benign* and *hostile* are the (floor, ceiling) the range would read on
    each outcome. *record* marks the one cue that improves a held record
    rather than closing an unearned dimension. *fed* is whether SPECTRE can
    take what it collects into the model today; the screen names only fed cues.
    """

    observation: str
    dimensions: tuple[Dimension, ...]
    steps: int
    hours: float
    effect: str
    benign: tuple[Band, Band]
    hostile: tuple[Band, Band]
    record: bool = False
    fed: bool = True

    @property
    def steps_per_hour(self) -> float:
        return self.steps / self.hours

    @property
    def inside_spectre(self) -> bool:
        """Whether SPECTRE collects it itself, a query it runs. The record cue needs an analyst; no cue yet needs a
        sensor, since no collection here tasks one (SPC-171)."""
        return not self.record


def _roots(result: ThreatRange) -> set[str]:
    return {row.item.derived_from for row in result.ledger}


def _held(roots: Iterable[str], prefix: str) -> list[str]:
    return sorted(root for root in roots if root.startswith(prefix))


def _identity_collection(roots: set[str]) -> _Collection:
    """The GCAT entry: Identity coverage only, a refresh of the held entry when there is one."""
    held = _held(roots, _GCAT_ROOT)
    verb = "refresh" if held else "pull"
    probe = _Probe(Dimension.IDENTITY, held[0] if held else f"{_PROBE_ROOT}gcat", _GCAT_GRADE, _GCAT_CREDIBILITY,
                   CATALOGUE_FIELD_EXTRACTION, Basis.LOOKUP)
    return _Collection(f"{verb} its GCAT catalogue entry", _GCAT_HOURS, (probe,))


def _history_collection(roots: set[str], unearned: set[Dimension]) -> _Collection | None:
    """An element-set history: the first, from the 18 SDS catalogue, or a second provider's, commercial.

    In Capability it could read a spent tank (the most benign: ceiling
    MINIMAL); in Behaviour an unprecedented burn (the most hostile: floor
    HIGH). Only its unearned dimensions are probed.
    """
    second = bool(_held(roots, _HISTORY_ROOT))
    grade = _UNLISTED_PROVIDER_GRADE if second else PROVIDER_GRADES[_18SDS]
    root = f"{_PROBE_ROOT}{'second provider' if second else 'history'}"
    shared: dict[str, Any] = {"root": root, "source_grade": grade, "credibility": _PROVIDER_CREDIBILITY,
                              "basis": Basis.COMPUTED, "controlled": grade in _CONTROLLED_GRADES}
    probes = tuple(probe for probe in (
        _Probe(Dimension.CAPABILITY, extraction=ASSUMED_FIGURE_EXTRACTION, benign_ceiling=Band.MINIMAL, **shared),
        _Probe(Dimension.BEHAVIOUR, extraction=DETECTION_EXTRACTION["HIGH"],
               hostile_floor=_HOSTILE_FLOOR[Normality.UNPRECEDENTED], **shared),
    ) if probe.dimension in unearned)
    if not probes:
        return None
    observation = "pull a second provider's element-set history" if second else PULL_HISTORY
    return _Collection(observation, _HISTORY_HOURS, probes, fed=not second)


def _conjunction_collection() -> _Collection:
    """UDL conjunctions held for the object: an approach caused by a burn reads floor HIGH (section 5.4)."""
    probe = _Probe(Dimension.INTERACTIONS, f"{_PROBE_ROOT}conjunctions", PROVIDER_GRADES[_18SDS],
                   _PROVIDER_CREDIBILITY, DETECTION_EXTRACTION["HIGH"], Basis.COMPUTED, controlled=True,
                   hostile_floor=Band.HIGH)
    return _Collection("hold UDL conjunctions for it", _CONJUNCTION_HOURS, (probe,), fed=False)


def _record_collections(result: ThreatRange, prior: Band | None) -> list[_Collection]:
    """An undated intel record, dated and sourced by an analyst (section 7.3).

    *prior* is the floor it would then set: MEDIUM for a HIGH or CRITICAL
    threat level, None for any other, which dated firms up Identity alone (section 5.1).
    """
    undated = sorted({row.item.derived_from for row in result.ledger
                      if row.item.derived_from.startswith(_RECORD_ROOT) and row.item.observed_at is None})
    return [_Collection("analyst to date and source the intel record", _RECORD_HOURS, (_Probe(
        Dimension.IDENTITY, root, _INTEL_GRADE, _INTEL_CREDIBILITY, ASSESSED_LABEL_EXTRACTION, Basis.LOOKUP,
        hostile_floor=prior),), record=True) for root in undated]


def _collections(result: ThreatRange, situation: Situation) -> list[_Collection]:
    """What could be collected: one collection per unearned dimension's source, and the record cue."""
    unearned = {d for d, u in result.coverage.items() if depth(u) is not Depth.EARNED}
    roots = _roots(result)
    history = _history_collection(roots, unearned)
    return [
        *([_identity_collection(roots)] if Dimension.IDENTITY in unearned else []),
        *([history] if history is not None else []),
        *([_conjunction_collection()] if Dimension.INTERACTIONS in unearned else []),
        *_record_collections(result, situation.record_prior),
    ]


def _effect(now: ThreatRange, benign: ThreatRange, hostile: ThreatRange, dimensions: tuple[Dimension, ...]) -> str:
    parts = [
        *([f"raise the Threat floor to {hostile.floor.name}"] if hostile.floor > now.floor else []),
        *([f"lower the Threat ceiling to {benign.ceiling.name}"] if benign.ceiling < now.ceiling else []),
    ]
    if parts:
        return "could " + " or ".join(parts)
    return f"would firm up {' and '.join(d.value for d in dimensions)} and move no Threat band"


def _cue(items: tuple[EvidenceItem, ...], situation: Situation, now: ThreatRange, collection: _Collection) -> Cue:
    """Section 4.10 for one collection: the range on each outcome, and the steps it would remove."""
    benign, hostile = (
        threat_range((*items, *(p.item(situation.now, hostile=h) for p in collection.probes)), situation)
        for h in (False, True))
    swing = max(0, int(now.ceiling) - int(benign.ceiling)) + max(0, int(hostile.floor) - int(now.floor))
    dimensions = tuple(p.dimension for p in collection.probes)
    return Cue(
        observation=collection.observation, dimensions=dimensions, hours=collection.hours,
        steps=min(int(now.ceiling) - int(now.floor), swing), effect=_effect(now, benign, hostile, dimensions),
        benign=(benign.floor, benign.ceiling), hostile=(hostile.floor, hostile.ceiling), record=collection.record,
        fed=collection.fed,
    )


def _rank(cue: Cue) -> tuple[float, float, str]:
    """Most steps of range per hour first, then the quicker, then by name, so the order is the same every time."""
    return -cue.steps_per_hour, cue.hours, cue.observation


def cues(items: Iterable[EvidenceItem], situation: Situation) -> tuple[Cue, ...]:
    """What to collect next, the most steps of range per hour first (section 4.10 and I11)."""
    held = tuple(items)
    now = threat_range(held, situation)
    found = [_cue(held, situation, now, collection) for collection in _collections(now, situation)]
    return tuple(sorted(found, key=_rank))


def _duration(hours: float) -> str:
    return f"{hours * _MINUTES_PER_HOUR:.0f} min" if hours < 1.0 else age_text(hours)


# ── Collect first (section 4.10, read by the Decision Engine, SPC-171) ────────

#: The action line A: the Threat band at which the operator's recommended response changes. The operator's to set;
#: HIGH until they do. Tuned, not sourced.
ACTION_LINE: Band = Band.HIGH


class Advice(Enum):
    """What the threat range says to do before deciding, against the action line."""

    COLLECT_FIRST = "collect first"
    ACT_ON_CEILING = "act on the ceiling"
    BELOW_ACTION_LINE = "below the action line"


@dataclass(frozen=True)
class CollectionAdvice:
    """The advice, the cue it names when it is to collect first, and the sentence the operator reads."""

    advice: Advice
    cue: Cue | None
    sentence: str


def _when(moment: datetime) -> str:
    """A moment as decide-by writes it: "15:00 UTC on 4 Nov"."""
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def _narrows(cue: Cue) -> bool:
    """A cue that could move a band, whose result SPECTRE can read: anything else leaves the range on screen as it is."""
    return cue.steps > 0 and cue.fed


def _decides(cue: Cue, action_line: Band) -> bool:
    """A cue with an outcome that takes the range off the action line: its benign ceiling falls under it, or its
    hostile floor reaches it. One that leaves the range across the line either way cannot change the decision."""
    return cue.benign[1] < action_line or cue.hostile[0] >= action_line


def landing_cues(cues: Iterable[Cue], *, now: datetime, decide_at: datetime | None,
                 action_line: Band = ACTION_LINE) -> tuple[Cue, ...]:
    """The cues that could move the range off *action_line*, whose result SPECTRE can read, landing by *decide_at*,
    best first.

    None with no decide-by: no cue can be shown to land in time.
    """
    if decide_at is None:
        return ()
    return tuple(sorted(
        (c for c in cues if _narrows(c) and _decides(c, action_line) and now + timedelta(hours=c.hours) <= decide_at),
        key=_rank,
    ))


def _no_cue_in_time(narrowing: list[Cue], deciding: list[Cue], decide_at: datetime | None, now: datetime) -> str:
    """Why nothing is collected first, though the range straddles the line."""
    if decide_at is None:
        return "no decide-by is set to collect against"
    if decide_at <= now:
        return "decide-by has passed"
    if not narrowing:
        return "no collection SPECTRE can read would narrow it"
    if not deciding:
        return "no collection SPECTRE can read could move it off that line"
    return f"no collection SPECTRE can read lands before decide-by at {_when(decide_at)}"


def collection_advice(span: tuple[Band, Band], cues: Iterable[Cue], *, now: datetime, decide_at: datetime | None,
                      action_line: Band = ACTION_LINE) -> CollectionAdvice:
    """Section 4.10: collect first, act on the ceiling, or below the action line, for the range *span*, its
    (floor, ceiling).

    Collect first only when the range straddles the line (floor below it, ceiling at or above it) and a cue that
    could move the range off the line on one of its outcomes, whose result SPECTRE can read, lands by decide-by: the
    best such cue by steps per hour is named. *decide_at* is the sweep's decide-by, which already subtracts the
    response time, so nothing is taken off again; with none set, no cue can be shown to land in time, so the cautious
    reading acts on the ceiling.
    """
    floor, ceiling = span
    line = f"Threat {action_line.name}, where your response changes"
    if ceiling < action_line:
        return CollectionAdvice(Advice.BELOW_ACTION_LINE, None,
                                f"Below the action line: the Threat ceiling is {ceiling.name}, under {line}.")
    act = f"Act on the ceiling: treat it as Threat {ceiling.name}."
    if floor >= action_line:
        return CollectionAdvice(Advice.ACT_ON_CEILING, None, f"{act} The Threat floor is already {floor.name}, at or "
                                f"above {line}, so no collection changes the decision.")
    runs = f"The Threat range runs from {floor.name} to {ceiling.name}, across {line}"
    held = tuple(cues)
    landing = landing_cues(held, now=now, decide_at=decide_at, action_line=action_line)
    if not landing or decide_at is None:
        narrowing = [c for c in held if _narrows(c)]
        why = _no_cue_in_time(narrowing, [c for c in narrowing if _decides(c, action_line)], decide_at, now)
        return CollectionAdvice(Advice.ACT_ON_CEILING, None, f"{act} {runs}, and {why}.")
    cue = landing[0]
    return CollectionAdvice(Advice.COLLECT_FIRST, cue, (
        f"Collect first: {cue.observation}, about {_duration(cue.hours)}, lands before decide-by at "
        f"{_when(decide_at)}. {runs}, and this {cue.effect}."
    ))


def cue_text(cue: Cue, *, threat: bool = True) -> str:
    """A cue as the operator reads it: the observation, what it could do, the steps and the time.

    With *threat* False, on a panel with no intercept and so no ACCESS to
    bound the range by, it names the dimensions it would firm up instead of
    Threat bands and steps worked out against a ceiling no geometry has set.
    """
    if not threat:
        firms = " and ".join(d.value for d in cue.dimensions)
        return f"{cue.observation}: would firm up {firms}, about {_duration(cue.hours)}"
    steps = "step" if cue.steps == 1 else "steps"
    return f"{cue.observation}: {cue.effect}, {cue.steps} Threat {steps}, about {_duration(cue.hours)}"


#: The signals the Missing list names when none is held, each by the root its items arrive under.
_SIGNALS: tuple[tuple[str, str], ...] = (
    (_RECORD_ROOT, "no intel record held"),
    (_GCAT_ROOT, "no GCAT catalogue entry held"),
    (_HISTORY_ROOT, "no element-set history held"),
)


def missing(result: ThreatRange) -> tuple[str, ...]:
    """Section 6.4's Missing list: the dimensions not earned, then the signals not held."""
    held = [row.item for row in result.ledger]
    roots = _roots(result)
    capability_chains = {i.derived_from for i in held
                         if i.dimension is Dimension.CAPABILITY and i.derived_from.startswith(_HISTORY_ROOT)}
    history = bool(_held(roots, _HISTORY_ROOT))
    return (
        *(f"{d.value} {depth(u).value}" for d, u in result.coverage.items() if depth(u) is not Depth.EARNED),
        *(text for root, text in _SIGNALS if not _held(roots, root)),
        *(["no second provider's history"] if history and len(capability_chains) < _MIN_SOURCE_CHAINS else []),
        *([] if any(i.source_grade == "A" for i in held) else ["no own or allied sensor track"]),
        *([] if any(i.dimension is Dimension.INTERACTIONS for i in held) else ["no approaches or conjunctions held"]),
        *([] if _held(roots, _PHOTOMETRY_ROOT) else ["photometry not uploaded"]),
        *([] if _held(roots, _NOTSO_ROOT) else ["no NOTSO filing held"]),
    )


# ── Words for the screen (SPC-166) ────────────────────────────────────────────
#
# Section 6.4 and I13: every band is labelled "Threat", in sentences of its
# own; Understanding's statement is built above. No percentage is written.


def threat_sentence(result: ThreatUnderstanding) -> str:
    """The Threat line: the assessed point and how far it could move, or the ceiling when it cannot be called."""
    span, verdict = result.range, result.verdict
    if verdict.at_ceiling:
        if span.ceiling_support == _ACCESS_SUPPORT:
            return f"Threat: cannot assess beyond access ({span.ceiling.name})."
        return f"Threat: cannot assess beyond the ceiling the evidence allows ({span.ceiling.name})."
    parts = [f"Threat: assessed {verdict.assessed.name}."]
    if span.floor < verdict.assessed:
        parts.append(f"Threat could be as low as {span.floor.name}.")
    if span.ceiling > verdict.assessed:
        parts.append(f"Threat could be as high as {span.ceiling.name}.")
    return " ".join(parts)


def reading_text(item: EvidenceItem) -> str:
    """What an item would do to the range, labelled Threat: a floor, a ceiling, or coverage only."""
    if item.floor_to is not None:
        return f"Threat floor {item.floor_to.name}"
    if item.ceiling_to is not None:
        return f"Threat ceiling {item.ceiling_to.name}"
    return "coverage only"
