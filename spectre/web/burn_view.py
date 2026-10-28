"""How a burn is described: its dominant axis and the intent its method implies.

The intercept panel and the threat sweep each kept a copy of the axis rule
and a table of intent labels, and the two had drifted (audit F-241). This is
the one copy.
"""

from __future__ import annotations

from spectre.domain.models import InterceptMethod

#: A component carrying at least this share of the burn magnitude names the
#: axis on its own; below it the burn is reported as "Combined".
DOMINANT_AXIS_FRACTION: float = 0.7


def dominant_axis(pro: float, nor: float, rad: float, threshold: float) -> str:
    """Name the axis carrying the burn, or "Combined" when none dominates.

    The ladder is tested prograde, then normal, then radial, and the first
    component at or above *threshold* wins. That order is the reported one and
    matters when two components are both above it.
    """
    if abs(pro) >= threshold:
        return "Prograde" if pro >= 0 else "Retrograde"
    if abs(nor) >= threshold:
        return "Normal" if nor >= 0 else "Anti-normal"
    if abs(rad) >= threshold:
        return "Radial" if rad >= 0 else "Anti-radial"
    return "Combined"


_CLOSE_PROXIMITY_INTENT = "Close-Proximity Operation"

INTENT_LABELS: dict[InterceptMethod, str] = {
    InterceptMethod.LAMBERT: _CLOSE_PROXIMITY_INTENT,
    InterceptMethod.PROXIMITY: _CLOSE_PROXIMITY_INTENT,
    InterceptMethod.RENDEZVOUS: _CLOSE_PROXIMITY_INTENT,
    InterceptMethod.HOHMANN: "Orbital Transfer — Energy Change",
    InterceptMethod.BIELLIPTIC: "Orbital Transfer — Energy Change",
    InterceptMethod.PHASING: "Phasing Rendezvous",
    InterceptMethod.RBAR_HOP: "R-Bar Hop (Radial Proximity Approach)",
    InterceptMethod.VBAR_HOP: "V-Bar Hop Sequence (Along-Track Approach)",
    InterceptMethod.HBAR_HOP: "H-Bar Hop Sequence (Orbit-Normal Approach)",
    InterceptMethod.CW_DRIFT: "Proximity Manoeuvre (CW)",
    InterceptMethod.NMC: "Proximity Manoeuvre (CW)",
    InterceptMethod.PLANE_CHANGE: "Plane Change — Orbit Alignment",
    InterceptMethod.J2_DRIFT: "J2-Assisted RAAN Drift",
    InterceptMethod.COLA: "Collision Avoidance",
    InterceptMethod.GEO_DRIFT: "GEO Longitude Relocation",
    InterceptMethod.MANOEUVRE_DETECT: "Observed Manoeuvre — Classification",
    InterceptMethod.DETECTABILITY: "Detectability Assessment",
    InterceptMethod.EVASION: "Evasion Manoeuvre",
    InterceptMethod.INTENT_PREDICT: "Adversary Intent Assessment",
    InterceptMethod.INTERCEPT_ENVELOPE: "Intercept Reachability Envelope",
    InterceptMethod.STABILITY: "Relative Motion Stability Analysis",
    InterceptMethod.FINGERPRINT: "Behavioural Fingerprint Analysis",
    InterceptMethod.FORMATION: "Formation-Aware Defensive Burn",
    InterceptMethod.TERRAIN: "Orbital Terrain Risk Assessment",
    InterceptMethod.MIN_TIME: "Minimum-Time Intercept",
}


def intent_label_for(method: str, default: str) -> str:
    """The intent label for a method given by its string value."""
    try:
        return INTENT_LABELS.get(InterceptMethod(method), default)
    except ValueError:
        return default
