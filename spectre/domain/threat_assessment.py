"""Compose a threat verdict from geometry, capability and time.

Why this exists
---------------
The sweep's verdict was four thresholds on a delta-V number:

    dv < 0.2 -> CRITICAL, dv < 0.5 -> HIGH, dv < 1.0 -> MEDIUM, else LOW

and the summary line called that an "adversary capability assessment". It is
not one. A low delta-V means two orbits happen to be conveniently arranged. It
says nothing about whether the object at the other end can or would fly it, and
the application already held the evidence that would say so: an assessed threat
level and operational status per object, a behavioural anomaly score, a
propellant budget with remaining life, and a detected manoeuvre history. None
of it reached the verdict.

The consequence was visible on screen. An object assessed LOW and Degraded
still has a cheap geometric path to a co-orbital target, so the sweep scored it
CRITICAL while the intelligence panel beside it said the opposite, with nothing
reconciling the two.

What this module does
---------------------
Separates the two questions that were being conflated, answers each on its own
evidence, and combines them explicitly:

    ACCESS      does the geometry permit it, and how soon
    CAPABILITY  can this object actually do it
    VERDICT     both, with the weaker one governing

A threat needs both. A permissive geometry against a derelict is not a threat;
a highly capable object that cannot reach you is not a threat today.

Pure functions over plain data. No I/O, no framework, no globals, so every
branch is testable and the caller decides what evidence it can afford to
gather.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from enum import IntEnum

from spectre.domain.custody import Custody
from spectre.domain.manoeuvre_calibration import (
    ManoeuvreKind,
    Posture,
    PostureAssessment,
    classify_posture,
    fastest_delivery_hours,
    kind_for_method,
)
from spectre.domain.pol_assessment import anomaly_risk_level
from spectre.domain.provenance import Provenance, provenance, value_input

__all__ = [
    "AccessEvidence",
    "ActorVerdict",
    "Band",
    "CapabilityEvidence",
    "ConfidenceContext",
    "ScreeningResult",
    "ThreatAssessment",
    "assess_threat",
    "rank_actors",
    "warning_time_rank",
    "NON_ARRIVING_METHODS",
    "arrives_at_target",
]


class Band(IntEnum):
    """Severity, ordered so the weaker of two can be taken with ``min``."""

    MINIMAL = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name


# Geometric accessibility, derived from what the manoeuvre would actually cost
# an object in that regime rather than from four global numbers.
#
# The old thresholds were 200, 500 and 1,000 m/s. Every counterspace manoeuvre
# the assessment records as observed sits below the lowest of them: the
# Luch/Olymp-K 2 relocation cost 11 m/s and the SJ-21 tow of Beidou-2 G2, the
# largest, about 60 m/s one way and 120 m/s round trip. Table 4's worked example
# of a 90 degree GEO relocation in 3 days, about 170 m/s, is below it too. So
# the band returned CRITICAL for a routine commercial move and CRITICAL for a
# hostile closure alike, and a measurement that returns one answer for every
# input is not a measurement.
#
# Posture answers the question the thresholds were trying to ask. A manoeuvre
# the object could make inside its routine operating budget is the MOST
# permissive geometry there is, because it costs the adversary nothing it was
# not already spending.
_POSTURE_TO_ACCESS: dict[Posture, Band] = {
    Posture.BENIGN: Band.CRITICAL,
    Posture.ANNOYANCE: Band.HIGH,
    Posture.AGGRESSIVE: Band.MEDIUM,
    Posture.BEYOND_PLATFORM: Band.MINIMAL,
}

# Operational status strings that mean the object cannot be relied on to
# manoeuvre. Matched case-insensitively on a substring so "Inactive - Retired /
# Not Manoeuverable" and "Degraded" both land.
_IMPAIRED_STATUS_MARKERS: tuple[str, ...] = (
    "degraded", "inactive", "retired", "non-operational", "not manoeuv",
    "decayed", "failed", "tumbling",
)

# Propellant remaining below this is treated as unable to sustain an intercept.
#
# This threshold was dead in both directions before the Pattern of Life
# propellant model was rebuilt. The delta-V feeding it was measuring along-track
# phase, so every analysed object reported 100 per cent consumed and was graded
# incapable while actively manoeuvring. Correcting the delta-V did not fix it:
# the figure was the fraction of TOTAL SPACECRAFT MASS, which needs 9.40 km/s of
# cumulative spend to reach 95 per cent against a practical ceiling of 2.5, so
# the band could then never fire at all. It now reads the fraction of the
# PROPELLANT LOAD, which is reachable: about 1.57 km/s for a LEO smallsat and
# 0.85 km/s for a chemical GEO comsat, both inside Table 2's envelopes.
_PROPELLANT_SPENT_PCT: float = 95.0
# Propellant remaining at or above this grades capability HIGH; below it, LOW,
# so a scarce reserve cannot raise an assessed LOW (it graded MEDIUM, audit
# F-120). Tuned, not sourced.
_PROPELLANT_AMPLE_PCT: float = 50.0
# The same cut applied to the discretionary reserve, as a share rather than a
# percentage because that reading divides remaining by maximum directly. Half
# the reserve still unspent is a platform that can still act against someone.
_DISCRETIONARY_AMPLE_SHARE: float = 0.5

# A platform can hold propellant and still be unable to act: most of a GEO
# comsat's remaining tank is committed to fifteen years of station-keeping, and
# Table 2 puts its DISCRETIONARY reserve at 50 to 200 m/s. Spending that is
# what removes the ability to manoeuvre against someone, which is the question
# a capability verdict is actually asking.
_DISCRETIONARY_EXHAUSTED_M_S: float = 0.0

# ── Confidence: how well founded the verdict is (SPC-160) ───────────────────
#
# Confidence was a count of inputs: four or more read HIGH, and orbital
# geometry was one of the four. So an object with no intel record and a
# history showing no burns read HIGH on geometry, a regime-assumed full tank
# counted twice (propellant used and discretionary reserve) and "0 burns".
# The four figures a history gives come from one source chain, and agreement
# among copies is not corroboration (Dong, Berti-Equille and Srivastava,
# PVLDB 2(1), 2009). Geometry is the question being asked, not evidence about
# the satellite. Confidence now counts what is known about the satellite, by
# independent source, once each: the interim rule the Threat Understanding
# concept (docs/threat_confidence_concept.md, section 6) replaces in full at
# SPC-162 to SPC-164.


class _Level(IntEnum):
    """Confidence, ordered so the weakest limit can be taken with ``min``.

    MODERATE, not MEDIUM, as UK assessment practice names its middle level,
    so a confidence never reads like a threat band.
    """

    LOW = 0
    MODERATE = 1
    HIGH = 2


#: The independent sources the six capability inputs come from.
_RECORD = "the assessed record"
_HISTORY = "the element-set history"

#: What a source tells us about the satellite, in the concept's dimensions.
_IDENTITY, _CAPABILITY, _BEHAVIOUR = "identity", "capability", "behaviour"
_DIMENSIONS: tuple[str, ...] = (_IDENTITY, _CAPABILITY, _BEHAVIOUR)

# All three dimensions held reads HIGH, two read MODERATE, after the concept's
# Information Base criteria (section 6.1). Tuned, not sourced.
_DIMENSIONS_FOR_HIGH: int = 3
_DIMENSIONS_FOR_MODERATE: int = 2

# The interceptor's custody caps confidence: a picture that cannot be kept
# current is not a well-founded one (section 6.1, Complexity and Volatility).
# Not assessed reads as not HIGH. Tuned, not sourced.
_CUSTODY_CAP: dict[Custody | None, _Level] = {
    Custody.HELD: _Level.HIGH,
    Custody.DEGRADED: _Level.MODERATE,
    Custody.LOST: _Level.LOW,
    None: _Level.MODERATE,
}
_CUSTODY_REASON: dict[Custody | None, str] = {
    Custody.DEGRADED: "custody of the interceptor is degraded",
    Custody.LOST: "custody of the interceptor is lost",
    None: "custody was not assessed",
}

# Live tracking is the only data mode that does not cap. A set entered by hand
# caps at the operator's stated confidence; one with none stated, and a mode
# not recorded, cap at MODERATE; every other mode (SYNTHETIC, TEST, EXERCISE,
# SIMULATED) describes the exercise, not the satellite, and reads LOW
# (section 6.2). Tuned, not sourced.
_LIVE_MODE = "REAL"
_MANUAL_MODE = "MANUAL"
_UNRECORDED_MODES: frozenset[str] = frozenset({"", "UNKNOWN"})
_MANUAL_CAP: dict[str, _Level] = {
    "CONFIRMED": _Level.HIGH,
    "HIGH": _Level.HIGH,
    "MEDIUM": _Level.MODERATE,
    "LOW": _Level.LOW,
    "UNCONFIRMED": _Level.LOW,
}

# Two readings that contradict each other leave the picture unsettled, so a
# conflict caps confidence (section 4.7). Tuned, not sourced.
_CONFLICT_CAP: _Level = _Level.MODERATE

# The behavioural anomaly score is graded through the Pattern of Life ladder
# (pol_assessment._RISK_LADDER), so one score reads one band in both panels.
# It had cut-offs of its own, 60 and 80, and any score, 0 included, graded
# capability at least MEDIUM (audit F-120). The ladder's rungs are tuned, not
# sourced; see pol_assessment.


@dataclass(frozen=True)
class AccessEvidence:
    """What the geometry permits, how much warning it leaves, and at what cost.

    Delta-v is in METRES PER SECOND. The astro package computes in km/s and the
    conversion happens once, at the route boundary, via
    ``manoeuvre_calibration.from_km_s``. Nothing downstream of that multiplies
    by 1,000 again.
    """

    best_delta_v_m_s: float
    time_to_arrival_hours: float
    method: str = ""
    regime: str = ""

    @property
    def kind(self) -> ManoeuvreKind:
        """The operational kind of manoeuvre the winning method represents."""
        return kind_for_method(self.method)

    def posture(self) -> PostureAssessment:
        """What this cost says about how the actor would have to behave."""
        return classify_posture(self.best_delta_v_m_s, self.regime, self.kind)

    def is_physically_deliverable(self) -> tuple[bool, str]:
        """False when no flown platform could deliver this burn in the time.

        The transfer solvers are impulsive. Against a chemical platform over
        several hours that is fair. Against an all-electric bus at millinewton
        thrust it is not an approximation but the wrong question, so a solution
        whose time of flight is shorter than the fastest possible delivery is
        not flyable by anything currently in orbit.
        """
        hours, who = fastest_delivery_hours(self.best_delta_v_m_s)
        if hours <= self.time_to_arrival_hours:
            return (True, "")
        if hours == float("inf"):
            return (False, (
                f"{self.best_delta_v_m_s:.0f} m/s is beyond the largest platform "
                "total in the assessment's Table 2"
            ))
        return (False, (
            f"no flown platform could deliver {self.best_delta_v_m_s:.0f} m/s "
            f"in the {self.time_to_arrival_hours:.1f} h this transfer assumes; "
            f"the fastest ({who}) needs {hours:.1f} h of continuous thrust"
        ))

    def band(self) -> Band:
        """How permissive the geometry is. Nothing to do with the adversary.

        A manoeuvre that is undeliverable in the time available is not a
        permissive geometry at any price, so it floors at MINIMAL.
        """
        deliverable, _ = self.is_physically_deliverable()
        if not deliverable:
            return Band.MINIMAL
        return _POSTURE_TO_ACCESS[self.posture().posture]


@dataclass(frozen=True)
class CapabilityEvidence:
    """What is known about the object's ability to act.

    Every field is optional because the caller may not have been able to gather
    it. Absence is carried through to the confidence of the verdict rather than
    being silently treated as either capable or incapable.
    """

    intel_threat_level: str | None = None      # from the assessed record
    #: True when the assessed record carries a date. None of the 44 bundled
    #: records does, so nothing sets it yet (concept section 5, SPC-165).
    intel_record_dated: bool = False
    operational_status: str | None = None      # "Operational", "Degraded", ...
    #: Fraction of the PROPELLANT LOAD consumed, from PropellantAssessment.
    #: Not the fraction of total spacecraft mass, which is what the field used
    #: to carry and which differs by the propellant mass fraction: a factor of
    #: ten for a LEO smallsat.
    propellant_used_pct: float | None = None
    #: Discretionary reserve left, m/s, from PropellantAssessment. The better
    #: signal, because it is the budget a manoeuvre against someone comes out
    #: of rather than the tank as a whole.
    discretionary_remaining_m_s: float | None = None
    discretionary_max_m_s: float | None = None
    anomaly_score: float | None = None         # 0-100, from AnomalyAssessment
    manoeuvres_observed: int | None = None     # detected in the history window
    history_span_days: float | None = None

    def is_impaired(self) -> bool:
        """True when the assessed status says this object cannot manoeuvre."""
        if not self.operational_status:
            return False
        lowered = self.operational_status.lower()
        return any(marker in lowered for marker in _IMPAIRED_STATUS_MARKERS)

    def has_any_evidence(self) -> bool:
        return any(
            value is not None
            for value in (
                self.intel_threat_level, self.operational_status,
                self.propellant_used_pct, self.discretionary_remaining_m_s,
                self.anomaly_score,
                self.manoeuvres_observed,
            )
        )

    def _incapacity(self) -> Band | None:
        """MINIMAL when something says this object cannot act, else None.

        A stated inability to manoeuvre, or a spent tank, dominates every other
        signal: whatever the geometry permits, this object is not flying it.
        """
        if self.is_impaired():
            return Band.MINIMAL
        if (
            self.propellant_used_pct is not None
            and self.propellant_used_pct >= _PROPELLANT_SPENT_PCT
        ):
            return Band.MINIMAL
        if (
            self.discretionary_remaining_m_s is not None
            and self.discretionary_remaining_m_s <= _DISCRETIONARY_EXHAUSTED_M_S
        ):
            return Band.MINIMAL
        return None

    def recognised_threat_level(self) -> Band | None:
        """The assessed threat level as a band, or None when absent or unrecognised.

        An unrecognised label is NO evidence, not low evidence, so a typo or a
        new label cannot quietly downgrade an object.
        """
        if not self.intel_threat_level:
            return None
        with contextlib.suppress(KeyError):
            return Band[self.intel_threat_level.strip().upper()]
        return None

    def _signals(self) -> list[Band]:
        """Every capability signal this object offers, as a severity each."""
        candidates: list[Band] = []

        assessed = self.recognised_threat_level()
        if assessed is not None:
            candidates.append(assessed)

        if self.anomaly_score is not None:
            candidates.append(Band[anomaly_risk_level(self.anomaly_score)])

        # The discretionary reserve is the better reading where it is
        # available, because it is the budget a manoeuvre against someone comes
        # out of. Fall back to the tank only when it is not.
        if (self.discretionary_remaining_m_s is not None
                and self.discretionary_max_m_s is not None
                and self.discretionary_max_m_s > 0):
            share = self.discretionary_remaining_m_s / self.discretionary_max_m_s
            candidates.append(
                Band.HIGH if share >= _DISCRETIONARY_AMPLE_SHARE else Band.LOW
            )
        elif self.propellant_used_pct is not None:
            remaining = 100.0 - self.propellant_used_pct
            candidates.append(
                Band.HIGH if remaining >= _PROPELLANT_AMPLE_PCT else Band.LOW
            )

        if self.manoeuvres_observed is not None and self.manoeuvres_observed > 0:
            candidates.append(Band.MEDIUM)

        return candidates

    def band(self) -> Band | None:
        """Capability severity, or None when nothing is known.

        None is not the same as MINIMAL, and conflating them is how a verdict
        starts quietly under-reporting objects nobody has assessed yet.
        """
        if not self.has_any_evidence():
            return None

        incapacity = self._incapacity()
        if incapacity is not None:
            return incapacity

        candidates = self._signals()
        if not candidates:
            return None
        # The strongest single indication governs: an object with one alarming
        # signal and several unremarkable ones is still worth attention.
        return max(candidates)


@dataclass(frozen=True)
class ThreatAssessment:
    """The composed verdict, with its workings visible.

    ``rationale`` and ``inputs_missing`` exist so the analyst can see which
    evidence produced the answer, and which was absent. A verdict that cannot
    be interrogated gets ignored the first time it disagrees with the operator.
    """

    verdict: Band
    access: Band
    capability: Band | None
    warning_time_hours: float
    confidence: str
    rationale: str
    inputs_used: list[str] = field(default_factory=list)
    inputs_missing: list[str] = field(default_factory=list)
    #: What the required delta-v says about how the actor would have to behave,
    #: and the published figures that band came from.
    posture_label: str = ""
    posture_rationale: str = ""
    posture_basis: str = ""
    #: Set when no flown platform could deliver the burn in the time available.
    undeliverable_reason: str = ""
    #: The code, calibration and evidence behind this verdict (audit F-121).
    provenance: Provenance | None = None
    #: What ``confidence`` rests on, source by source, and what holds it down.
    confidence_basis: str = ""
    #: Two readings that contradict each other, named; empty when none do.
    confidence_conflict: str = ""

    @property
    def verdict_label(self) -> str:
        return self.verdict.label

    @property
    def access_label(self) -> str:
        return self.access.label

    @property
    def capability_label(self) -> str:
        return self.capability.label if self.capability is not None else "UNASSESSED"


@dataclass(frozen=True)
class ConfidenceContext:
    """What bears on confidence without being evidence about the satellite.

    *data_mode* is the UDL dataMode of the interceptor's element set, MANUAL
    for one entered by hand, ``None`` when not recorded. *manual_confidence*
    is the operator's stated confidence in a hand-entered set. *custody* is
    the interceptor's custody by the shared rule, ``None`` when not assessed.
    """

    data_mode: str | None = None
    custody: Custody | None = None
    manual_confidence: str | None = None


def _dimensions_by_source(capability: CapabilityEvidence) -> dict[str, list[str]]:
    """What each independent source tells us about the satellite, counted once per dimension.

    The operational status is declared by the object's operator and is not
    counted; nor is "no burns observed", an absence rather than a reading.
    An undated record is not counted either: taken as one half-life old, a
    single-source record scores 0.09, below the 0.25 an item needs to
    establish a dimension (concept sections 4.3 and 4.12, row 1).
    """
    held: dict[str, list[str]] = {}
    if capability.recognised_threat_level() is not None and capability.intel_record_dated:
        held[_RECORD] = [_IDENTITY]
    history: list[str] = []
    if capability.propellant_used_pct is not None or capability.discretionary_remaining_m_s is not None:
        history.append(_CAPABILITY)
    if capability.anomaly_score is not None or (capability.manoeuvres_observed or 0) > 0:
        history.append(_BEHAVIOUR)
    if history:
        held[_HISTORY] = history
    return held


def _not_counted(capability: CapabilityEvidence) -> list[str]:
    """The inputs present that add nothing to confidence, each with the reason."""
    reasons: list[str] = []
    if capability.intel_threat_level and capability.recognised_threat_level() is None:
        reasons.append(_unrecognised_label(capability.intel_threat_level))
    elif capability.intel_threat_level and not capability.intel_record_dated:
        reasons.append("the assessed record, which carries no date, so cannot establish identity")
    if capability.operational_status:
        reasons.append(f"the recorded status '{capability.operational_status}', which is declared, not observed")
    if capability.manoeuvres_observed == 0:
        reasons.append("no burns observed, an absence rather than a reading")
    return reasons


def _unrecognised_label(label: str) -> str:
    return f"assessed threat level ('{label}' is not a recognised band)"


def _conflict(capability: CapabilityEvidence) -> str:
    """A status saying the object cannot manoeuvre, against a history showing it does."""
    burns = capability.manoeuvres_observed or 0
    if not (capability.is_impaired() and burns > 0):
        return ""
    plural = "burn" if burns == 1 else "burns"
    return (f"the record says {capability.operational_status}, but the history shows {burns} {plural}: "
            "possible deception")


def _information_base(held: dict[str, list[str]]) -> tuple[_Level, str]:
    """The level the dimensions held support, and what is missing when it is not HIGH."""
    dimensions = [d for d in _DIMENSIONS if any(d in found for found in held.values())]
    missing = ", ".join(d for d in _DIMENSIONS if d not in dimensions)
    if len(dimensions) >= _DIMENSIONS_FOR_HIGH:
        return _Level.HIGH, ""
    if len(dimensions) >= _DIMENSIONS_FOR_MODERATE:
        return _Level.MODERATE, f"{missing} not held"
    return _Level.LOW, f"{missing} not held"


def _data_mode_limit(context: ConfidenceContext) -> tuple[_Level, str]:
    """The cap the interceptor's element set's provenance puts on confidence."""
    mode = (context.data_mode or "").strip().upper()
    if mode == _LIVE_MODE:
        return _Level.HIGH, ""
    if mode in _UNRECORDED_MODES:
        return _Level.MODERATE, "the element set's data mode is not recorded"
    if mode == _MANUAL_MODE:
        stated = (context.manual_confidence or "").strip().upper()
        if stated not in _MANUAL_CAP:
            return _Level.MODERATE, "the element set was entered by hand with no stated confidence"
        return _MANUAL_CAP[stated], f"the element set was entered by hand at {stated} confidence"
    return _Level.LOW, f"computed from {mode} element sets: describes the exercise, not the satellite"


def _confidence(capability: CapabilityEvidence, context: ConfidenceContext) -> tuple[str, str, str]:
    """The confidence level, the sentence saying what it rests on, and any conflict.

    The level is the weakest of what the evidence supports, the data mode,
    custody and any conflict. Orbital geometry is not counted: it is the
    question being asked, not evidence about the satellite.
    """
    held = _dimensions_by_source(capability)
    conflict = _conflict(capability)
    limits = [
        _information_base(held),
        _data_mode_limit(context),
        (_CUSTODY_CAP[context.custody], _CUSTODY_REASON.get(context.custody, "")),
        (_CONFLICT_CAP, conflict) if conflict else (_Level.HIGH, ""),
    ]
    level = min(cap for cap, _ in limits)
    sentence = f"Confidence {level.name}. {_sources_clause(held)} Orbital geometry is not counted."
    not_counted = _not_counted(capability)
    if not_counted:
        sentence += f" Not counted: {'; '.join(not_counted)}."
    reasons = [reason for cap, reason in limits if cap < _Level.HIGH]
    if reasons:
        sentence += f" Not higher because: {'; '.join(reasons)}."
    return level.name, sentence, conflict


def _sources_clause(held: dict[str, list[str]]) -> str:
    """The independent sources confidence rests on, each named once with what it tells us."""
    if not held:
        return "Rests on 0 independent sources: nothing is held about the satellite itself."
    noun = "source" if len(held) == 1 else "sources"
    sources = "; ".join(f"{source} ({', '.join(dims)})" for source, dims in held.items())
    return f"Rests on {len(held)} independent {noun}, each counted once: {sources}."


def _inputs(capability: CapabilityEvidence) -> tuple[list[str], list[str]]:
    """The capability inputs used and missing; an unrecognised label is missing, with the reason."""
    used: list[str] = ["orbital geometry"]
    missing: list[str] = []
    for label, value in (
        ("assessed threat level", capability.recognised_threat_level()),
        ("operational status", capability.operational_status),
        ("propellant budget", capability.propellant_used_pct),
        # _signals reads it, so the verdict must list it (audit F-228).
        ("discretionary reserve", capability.discretionary_remaining_m_s),
        ("behavioural anomaly score", capability.anomaly_score),
        ("observed manoeuvre history", capability.manoeuvres_observed),
    ):
        (used if value is not None else missing).append(label)
    if capability.intel_threat_level and capability.recognised_threat_level() is None:
        missing[missing.index("assessed threat level")] = _unrecognised_label(capability.intel_threat_level)
    return used, missing


def _impairment_clause(capability: CapabilityEvidence) -> str:
    """The clause naming the recorded status, or empty when there is none.

    Guards on the status string as well as the impairment flag so the rationale
    can never read "recorded as None". The verdict is there to be interrogated,
    and a sentence that cites absent evidence is how an analyst learns to stop
    trusting it.
    """
    if capability.is_impaired() and capability.operational_status:
        return f" because the object is recorded as {capability.operational_status}"
    return ""


def assess_threat(access: AccessEvidence, capability: CapabilityEvidence,
                  context: ConfidenceContext | None = None) -> ThreatAssessment:
    """Compose the two into one verdict, showing the working.

    The rule is that the weaker of the two governs, because a threat needs both
    a permissive geometry and an object able to exploit it.

    The one exception is that an unassessed object is NOT treated as incapable.
    Where no capability evidence exists the verdict falls back to geometry
    alone and says so, with low confidence, rather than quietly scoring an
    unknown object as harmless.

    *context* carries what bears on confidence without being evidence about
    the satellite: the element set's data mode and the interceptor's custody.
    It never moves the verdict.
    """
    context = context or ConfidenceContext()
    access_band = access.band()
    capability_band = capability.band()
    used, missing = _inputs(capability)
    confidence, confidence_basis, conflict = _confidence(capability, context)

    if capability_band is None:
        verdict = access_band
        rationale = (
            f"Geometry permits an intercept at {access.best_delta_v_m_s:.0f} m/s "
            f"({access_band.label} accessibility). No capability evidence was available "
            "for this object, so the verdict reflects the geometry alone and may "
            "overstate the threat."
        )
    else:
        verdict = Band(min(access_band, capability_band))
        if capability_band < access_band:
            rationale = (
                f"Geometry permits an intercept at {access.best_delta_v_m_s:.0f} m/s "
                f"({access_band.label} accessibility), but capability is assessed "
                f"{capability_band.label}"
                + _impairment_clause(capability)
                + f". Verdict held at {verdict.label}."
            )
        elif capability_band > access_band:
            rationale = (
                f"Capability is assessed {capability_band.label}, but the geometry is "
                f"{access_band.label}: the cheapest path costs "
                f"{access.best_delta_v_m_s:.0f} m/s. Verdict held at {verdict.label}."
            )
        else:
            rationale = (
                f"Geometry and capability agree at {verdict.label}: an intercept costs "
                f"{access.best_delta_v_m_s:.0f} m/s and the object is assessed "
                "able to fly it."
            )

    posture = access.posture()
    deliverable, undeliverable_reason = access.is_physically_deliverable()

    # The posture sentence is the part an analyst can act on: it says what the
    # number means against cited regime figures and judgement bands placed
    # between them, rather than against one global threshold.
    rationale = f"{rationale} {posture.rationale}"
    if not deliverable:
        rationale = (
            f"{rationale} Flagged as not flyable: {undeliverable_reason}."
        )

    return ThreatAssessment(
        verdict=verdict,
        access=access_band,
        capability=capability_band,
        warning_time_hours=access.time_to_arrival_hours,
        confidence=confidence,
        rationale=rationale,
        inputs_used=used,
        inputs_missing=missing,
        posture_label=posture.posture_label,
        posture_rationale=posture.rationale,
        posture_basis=posture.basis,
        provenance=provenance([value_input("access", access), value_input("capability", capability),
                               value_input("confidence context", context)]),
        confidence_basis=confidence_basis,
        confidence_conflict=conflict,
        undeliverable_reason=undeliverable_reason,
    )


#: Methods whose solution aligns orbits without bringing the object to the
#: target. A plane change "arrives" the moment it burns, so its zero flight
#: time once ranked it the most dangerous course of action, arriving in under
#: a minute, whenever it fitted the budget.
NON_ARRIVING_METHODS: frozenset[str] = frozenset({"plane_change"})


def arrives_at_target(method: str) -> bool:
    """Whether a solution by *method* brings the object to the target."""
    return method not in NON_ARRIVING_METHODS


def warning_time_rank(
    entry_delta_v_m_s: float, tof_hours: float, budget_m_s: float, arrives: bool = True,
) -> tuple[float, float]:
    """Sort key that ranks on warning time, with feasibility as the filter.

    The sweep ranked on delta-V alone, so an intercept costing 120 m/s and
    taking 40 hours outranked one costing 450 m/s arriving in 35 minutes, and
    the second is by far the harder problem: warning time is what a defender
    actually spends.

    Delta-V keeps its role as the feasibility filter it already was. Anything
    outside the budget sorts last regardless of how quickly it would arrive,
    because an intercept that cannot be flown buys no warning at all. A
    solution that never reaches the target sorts last for the same reason.
    """
    feasible = 0 if entry_delta_v_m_s <= budget_m_s and arrives else 1
    return (feasible, tof_hours)


# ─────────────────────────────────────────────────────────────────────────────
# Screening one asset against many candidate actors
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActorVerdict:
    """One candidate actor's assessment against the asset being screened.

    ``assessment`` is the composed verdict. ``warning_hours`` and
    ``delta_v_m_s`` describe the entry that produced it, so the screen can show
    what the verdict was built from without re-deriving it.
    """

    actor_name: str
    actor_satno: str
    assessment: ThreatAssessment
    warning_hours: float
    delta_v_m_s: float
    method: str = ""
    country: str = ""

    @property
    def verdict(self) -> Band:
        return self.assessment.verdict

    @property
    def verdict_label(self) -> str:
        return self.assessment.verdict_label


@dataclass(frozen=True)
class ScreeningResult:
    """What screening an asset found, with its two headline answers.

    The two can disagree, and when they do the disagreement is the finding.
    """

    #: Every actor assessed, ranked worst first.
    ranked: list[ActorVerdict]
    #: The actor with the strongest composite verdict.
    most_dangerous: ActorVerdict | None
    #: The actor that would arrive soonest, whatever its assessed capability.
    earliest_arrival: ActorVerdict | None
    #: Set when those two are different objects.
    disagreement: str = ""


def _actor_rank_key(v: ActorVerdict) -> tuple[int, float, float]:
    """Worst first: strongest verdict, then least warning, then cheapest.

    Verdict leads because a derelict that happens to sit in a convenient orbit
    is not the thing to brief. Warning time breaks ties because among objects
    that could equally do it, the one arriving first is the harder problem.
    """
    return (-int(v.verdict), v.warning_hours, v.delta_v_m_s)


def rank_actors(verdicts: list[ActorVerdict]) -> ScreeningResult:
    """Rank candidate actors and name the two headline answers.

    Ranking on verdict alone would bury a fast approach behind a capability
    assessment that might be wrong. Ranking on warning time alone would put a
    derelict at the top and undo the whole point of the composite verdict.

    So both are computed and the disagreement is reported in words. If the
    object that could arrive soonest is not the object assessed most capable,
    an analyst needs to know that, because it is precisely the case where a
    wrong status field costs them their warning time.

    Nothing is ever dropped. An actor assessed MINIMAL is ranked last, not
    removed, for the same reason an unassessed object is not scored harmless:
    "nothing listed" and "nothing can reach you" must not look the same.
    """
    if not verdicts:
        return ScreeningResult(ranked=[], most_dangerous=None, earliest_arrival=None)

    ranked = sorted(verdicts, key=_actor_rank_key)
    most_dangerous = ranked[0]
    earliest_arrival = min(verdicts, key=lambda v: (v.warning_hours, v.delta_v_m_s))

    disagreement = ""
    if earliest_arrival.actor_satno != most_dangerous.actor_satno:
        disagreement = (
            f"These disagree. {most_dangerous.actor_name} is assessed "
            f"{most_dangerous.verdict_label} and would arrive in "
            f"{most_dangerous.warning_hours:.1f} h, but "
            f"{earliest_arrival.actor_name} could be here in "
            f"{earliest_arrival.warning_hours:.1f} h and is assessed "
            f"{earliest_arrival.verdict_label}. If that assessment is wrong, "
            f"your warning time is {earliest_arrival.warning_hours:.1f} h, not "
            f"{most_dangerous.warning_hours:.1f} h."
        )

    return ScreeningResult(
        ranked=ranked,
        most_dangerous=most_dangerous,
        earliest_arrival=earliest_arrival,
        disagreement=disagreement,
    )
