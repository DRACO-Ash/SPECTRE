"""How a delta-v figure is written for the operator. One place.

Everything the operator reads is in metres per second. The astro package works
in km/s internally and converts once, at the route boundary, so by the time a
number reaches a template it is already m/s and must never be scaled again.

Precision is deliberately modest. Measured against TLE uncertainty, a
co-orbital GEO intercept over six hours is good to about 1 m/s at a realistic
few-kilometre position error, so printing 182.34 m/s claims two digits that are
noise. Published manoeuvre figures are written the same way: the Luch/Olymp-K 2
relocation is "about 11 m/s", the SJ-21 tow "about 60 m/s".

Small burns are the exception. Proximity operations and collision avoidance run
from centimetres per second upward, and rounding those to zero would hide the
very manoeuvres the proximity band exists to describe.
"""

from __future__ import annotations

from spectre.domain.manoeuvre_calibration import from_km_s

__all__ = ["format_m_s", "format_tof_label", "to_m_s"]

#: Below this, a burn is small enough that the decimals carry the meaning.
_SMALL_BURN_M_S: float = 10.0


def format_m_s(value: float | None) -> str:
    """Format a delta-v in m/s, without claiming precision we do not have."""
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    magnitude = abs(v)
    if magnitude < 1.0:
        return f"{v:.2f}"
    if magnitude < _SMALL_BURN_M_S:
        return f"{v:.1f}"
    return f"{v:.0f}"


def to_m_s(value_km_s: float | None) -> float | None:
    """Convert a km/s figure from the astro layer into m/s for a template.

    Why this exists rather than ``* 1000`` in the template
    -----------------------------------------------------
    Templates used to scale inline, in eighteen places across four files. Each
    one was correct, and together they were a trap: the route layer ALSO
    converts at its boundary, so the first person to finish the job by
    converting a result object at the boundary would have left the template
    scaling an already-converted value. In one panel that would have put the
    charts at 1,000,000x and the table at 1,000x, both rendering without error.

    The invariant that removes the trap is simple enough to hold in your head
    and is enforced by a test: **no template performs unit arithmetic.** Every
    conversion happens in Python, at a named route boundary, and a template
    receives figures that are already in the unit of their name.

    None passes through, because a template that must render "-" for a missing
    value should not have to guard the conversion as well.
    """
    if value_km_s is None:
        return None
    return from_km_s(float(value_km_s))


_SECONDS_PER_MINUTE: float = 60.0
_SECONDS_PER_HOUR: float = 3600.0
_SECONDS_PER_DAY: float = 86400.0


def format_tof_label(tof_hours: float) -> str:
    """Render a flight time the way an operator reads it.

    The threat sweep and the intercept panel each carried their own copy of
    this chain. Two copies of a format is two places for them to drift, and an
    operator comparing the two screens would see the same duration written two
    ways without knowing which to trust.
    """
    tof_s = float(tof_hours) * _SECONDS_PER_HOUR
    if tof_s < _SECONDS_PER_MINUTE:
        return "< 1m"
    if tof_s < _SECONDS_PER_HOUR:
        return f"{int(tof_s // _SECONDS_PER_MINUTE)}m"
    if tof_s < _SECONDS_PER_DAY:
        h = int(tof_s // _SECONDS_PER_HOUR)
        m = int((tof_s % _SECONDS_PER_HOUR) // _SECONDS_PER_MINUTE)
        return f"{h}h {m}m" if m else f"{h}h"
    d = int(tof_s // _SECONDS_PER_DAY)
    h = int((tof_s % _SECONDS_PER_DAY) // _SECONDS_PER_HOUR)
    return f"{d}d {h}h" if h else f"{d}d"
