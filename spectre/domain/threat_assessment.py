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

from spectre.domain.manoeuvre_calibration import (
    ManoeuvreKind,
    Posture,
    classify_posture,
    fastest_delivery_hours,
    kind_for_method,
)

__all__ = [
    "AccessEvidence",
    "ActorVerdict",
    "Band",
    "CapabilityEvidence",
    "ScreeningResult",
    "ThreatAssessment",
    "assess_threat",
    "rank_actors",
    "warning_time_rank",
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
# on open record sits below the lowest of them: the Luch/Olymp-K 2 relocation
# cost 11 m/s, the SJ-21 tow of Beidou-2 G2 about 60 m/s, the most aggressive
# GEO repositioning measured about 170 m/s. So the band returned CRITICAL for
# a routine commercial move and CRITICAL for a hostile closure alike, and a
# measurement that returns one answer for every input is not a measurement.
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
_PROPELLANT_SPENT_PCT: float = 95.0
# Propellant remaining above this adds nothing; the object is simply capable.
_PROPELLANT_AMPLE_PCT: float = 50.0

# Geometry plus three capability inputs. Fewer than this and the verdict rests
# on an assessed label with little behaviour behind it.
_EVIDENCE_FOR_HIGH_CONFIDENCE: int = 4

# Behavioural anomaly above this is an object doing something unusual.
_ANOMALY_NOTABLE: float = 60.0
_ANOMALY_HIGH: float = 80.0


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

    def posture(self):  # -> PostureAssessment
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
                f"{self.best_delta_v_m_s:.0f} m/s is beyond the discretionary "
                "reserve of every platform class on open record"
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
    operational_status: str | None = None      # "Operational", "Degraded", ...
    propellant_used_pct: float | None = None   # from PropellantBudget
    anomaly_score: float | None = None         # 0-100, from AnomalyScore
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
                self.propellant_used_pct, self.anomaly_score,
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
        return None

    def _signals(self) -> list[Band]:
        """Every capability signal this object offers, as a severity each."""
        candidates: list[Band] = []

        if self.intel_threat_level:
            # An unrecognised label is NO evidence, not low evidence, so a typo
            # or a new label cannot quietly downgrade an object.
            with contextlib.suppress(KeyError):
                candidates.append(Band[self.intel_threat_level.strip().upper()])

        if self.anomaly_score is not None:
            if self.anomaly_score >= _ANOMALY_HIGH:
                candidates.append(Band.CRITICAL)
            elif self.anomaly_score >= _ANOMALY_NOTABLE:
                candidates.append(Band.HIGH)
            else:
                candidates.append(Band.MEDIUM)

        if self.propellant_used_pct is not None:
            remaining = 100.0 - self.propellant_used_pct
            candidates.append(
                Band.HIGH if remaining >= _PROPELLANT_AMPLE_PCT else Band.MEDIUM
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

    @property
    def verdict_label(self) -> str:
        return self.verdict.label

    @property
    def access_label(self) -> str:
        return self.access.label

    @property
    def capability_label(self) -> str:
        return self.capability.label if self.capability is not None else "UNASSESSED"


def assess_threat(access: AccessEvidence, capability: CapabilityEvidence) -> ThreatAssessment:
    """Compose the two into one verdict, showing the working.

    The rule is that the weaker of the two governs, because a threat needs both
    a permissive geometry and an object able to exploit it.

    The one exception is that an unassessed object is NOT treated as incapable.
    Where no capability evidence exists the verdict falls back to geometry
    alone and says so, with low confidence, rather than quietly scoring an
    unknown object as harmless.
    """
    access_band = access.band()
    capability_band = capability.band()

    used: list[str] = ["orbital geometry"]
    missing: list[str] = []

    for label, value in (
        ("assessed threat level", capability.intel_threat_level),
        ("operational status", capability.operational_status),
        ("propellant budget", capability.propellant_used_pct),
        ("behavioural anomaly score", capability.anomaly_score),
        ("observed manoeuvre history", capability.manoeuvres_observed),
    ):
        (used if value is not None else missing).append(label)

    if capability_band is None:
        verdict = access_band
        confidence = "LOW"
        rationale = (
            f"Geometry permits an intercept at {access.best_delta_v_m_s:.0f} m/s "
            f"({access_band.label} accessibility). No capability evidence was available "
            "for this object, so the verdict reflects the geometry alone and may "
            "overstate the threat."
        )
    else:
        verdict = Band(min(access_band, capability_band))
        confidence = "HIGH" if len(used) >= _EVIDENCE_FOR_HIGH_CONFIDENCE else "MEDIUM"
        if capability_band < access_band:
            rationale = (
                f"Geometry permits an intercept at {access.best_delta_v_m_s:.0f} m/s "
                f"({access_band.label} accessibility), but capability is assessed "
                f"{capability_band.label}"
                + (
                    f" because the object is recorded as {capability.operational_status}"
                    if capability.is_impaired() and capability.operational_status
                    else ""
                )
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
    # number means against what satellites actually do, rather than against a
    # threshold somebody picked.
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
        undeliverable_reason=undeliverable_reason,
    )


def warning_time_rank(entry_delta_v_m_s: float, tof_hours: float, budget_m_s: float) -> tuple[float, float]:
    """Sort key that ranks on warning time, with feasibility as the filter.

    The sweep ranked on delta-V alone, so an intercept costing 120 m/s and
    taking 40 hours outranked one costing 450 m/s arriving in 35 minutes, and
    the second is by far the harder problem: warning time is what a defender
    actually spends.

    Delta-V keeps its role as the feasibility filter it already was. Anything
    outside the budget sorts last regardless of how quickly it would arrive,
    because an intercept that cannot be flown buys no warning at all.
    """
    feasible = 0 if entry_delta_v_m_s <= budget_m_s else 1
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
