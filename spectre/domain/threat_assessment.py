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

from dataclasses import dataclass, field
from enum import IntEnum

__all__ = [
    "AccessEvidence",
    "Band",
    "CapabilityEvidence",
    "ThreatAssessment",
    "assess_threat",
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


# Geometric accessibility thresholds, in km/s. These are the original four and
# they are kept deliberately: as a measure of how permissive the geometry is
# they were never wrong, only mislabelled as a capability assessment.
_ACCESS_THRESHOLDS: tuple[tuple[float, Band], ...] = (
    (0.2, Band.CRITICAL),
    (0.5, Band.HIGH),
    (1.0, Band.MEDIUM),
)

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

# Behavioural anomaly above this is an object doing something unusual.
_ANOMALY_NOTABLE: float = 60.0
_ANOMALY_HIGH: float = 80.0


@dataclass(frozen=True)
class AccessEvidence:
    """What the geometry permits, and how much warning it leaves."""

    best_delta_v_km_s: float
    time_to_arrival_hours: float
    method: str = ""

    def band(self) -> Band:
        """How permissive the geometry is. Nothing to do with the adversary."""
        for threshold, band in _ACCESS_THRESHOLDS:
            if self.best_delta_v_km_s < threshold:
                return band
        return Band.LOW


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

    def band(self) -> Band | None:
        """Capability severity, or None when nothing is known.

        None is not the same as MINIMAL, and conflating them is how a verdict
        starts quietly under-reporting objects nobody has assessed yet.
        """
        if not self.has_any_evidence():
            return None

        # A stated inability to manoeuvre dominates everything else. Whatever
        # the geometry permits, this object is not going to fly it.
        if self.is_impaired():
            return Band.MINIMAL

        if self.propellant_used_pct is not None and self.propellant_used_pct >= _PROPELLANT_SPENT_PCT:
            return Band.MINIMAL

        candidates: list[Band] = []

        if self.intel_threat_level:
            try:
                candidates.append(Band[self.intel_threat_level.strip().upper()])
            except KeyError:
                pass  # an unrecognised label is no evidence, not low evidence

        if self.anomaly_score is not None:
            if self.anomaly_score >= _ANOMALY_HIGH:
                candidates.append(Band.CRITICAL)
            elif self.anomaly_score >= _ANOMALY_NOTABLE:
                candidates.append(Band.HIGH)
            else:
                candidates.append(Band.MEDIUM)

        if self.propellant_used_pct is not None:
            remaining = 100.0 - self.propellant_used_pct
            if remaining >= _PROPELLANT_AMPLE_PCT:
                candidates.append(Band.HIGH)
            else:
                candidates.append(Band.MEDIUM)

        if self.manoeuvres_observed is not None and self.manoeuvres_observed > 0:
            candidates.append(Band.MEDIUM)

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
            f"Geometry permits an intercept at {access.best_delta_v_km_s * 1000:.0f} m/s "
            f"({access_band.label} accessibility). No capability evidence was available "
            "for this object, so the verdict reflects the geometry alone and may "
            "overstate the threat."
        )
    else:
        verdict = Band(min(access_band, capability_band))
        confidence = "HIGH" if len(used) >= 4 else "MEDIUM"
        if capability_band < access_band:
            rationale = (
                f"Geometry permits an intercept at {access.best_delta_v_km_s * 1000:.0f} m/s "
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
                f"{access.best_delta_v_km_s * 1000:.0f} m/s. Verdict held at {verdict.label}."
            )
        else:
            rationale = (
                f"Geometry and capability agree at {verdict.label}: an intercept costs "
                f"{access.best_delta_v_km_s * 1000:.0f} m/s and the object is assessed "
                "able to fly it."
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
    )


def warning_time_rank(entry_delta_v_km_s: float, tof_hours: float, budget_km_s: float) -> tuple[float, float]:
    """Sort key that ranks on warning time, with feasibility as the filter.

    The sweep ranked on delta-V alone, so an intercept costing 0.12 km/s and
    taking 40 hours outranked one costing 0.45 km/s arriving in 35 minutes, and
    the second is by far the harder problem: warning time is what a defender
    actually spends.

    Delta-V keeps its role as the feasibility filter it already was. Anything
    outside the budget sorts last regardless of how quickly it would arrive,
    because an intercept that cannot be flown buys no warning at all.
    """
    feasible = 0 if entry_delta_v_km_s <= budget_km_s else 1
    return (feasible, tof_hours)
