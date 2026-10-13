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

__all__ = ["format_m_s"]

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
