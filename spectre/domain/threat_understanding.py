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

Every weight and threshold here is tuned, not sourced, and says so.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import KW_ONLY, dataclass
from datetime import datetime, timedelta
from enum import Enum, IntEnum

from spectre.domain.custody import Custody, age_text
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis, weakest
from spectre.domain.threat_assessment import Band

__all__ = [
    "ASSESSED_LABEL_EXTRACTION",
    "ASSUMED_FIGURE_EXTRACTION",
    "CATALOGUE_FIELD_EXTRACTION",
    "CREDIBILITY",
    "DETECTION_EXTRACTION",
    "EARNED",
    "MANUAL_EXTRACTION",
    "MANUFACTURABLE_CAP",
    "PARTIAL",
    "ROUTINE_CAP",
    "SOURCE_RELIABILITY",
    "Depth",
    "Dimension",
    "EvidenceItem",
    "HeldBurn",
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
    "coverage",
    "depth",
    "freshness",
    "half_life_days",
    "manual_extraction",
    "reliability",
    "threat_range",
    "understand",
    "verdict_for",
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
    """Threat as a range, Understanding as a rating, and the verdict they give."""

    range: ThreatRange
    understanding: UnderstandingRating
    verdict: Verdict


def assess(items: Iterable[EvidenceItem], situation: Situation) -> ThreatUnderstanding:
    """The threat range the evidence earns, how well founded it is, and the verdict."""
    result = threat_range(items, situation)
    rating = understand(result, situation)
    legacy = situation.access if situation.legacy is None else situation.legacy
    return ThreatUnderstanding(range=result, understanding=rating,
                               verdict=verdict_for(legacy, result.floor, result.ceiling, rating.level))
