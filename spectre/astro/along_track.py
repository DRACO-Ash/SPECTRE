"""Shift an element set along its orbit, and how far its position may be out.

The threat sweep printed delta-V as if it were exact. The red team measured
what element-set error does to it: about 0.2 m/s of spread per kilometre of
position error on a six-hour co-orbital GEO intercept (red team finding 6,
docs/RED-TEAM-THREAT-SWEEP.md). To give each figure a band, the sweep re-solves
it with each orbit moved along track by the error its element set is assumed
to carry, which grows with the set's age. Along track, because that is where
element-set error accumulates fastest.

The error model is tuned, not sourced: 1 km at epoch plus 2 km a day of age
for LEO and MEO, 2 km plus 1 km a day for GEO and deep space, where tracking
is sparser but the orbit changes more slowly. The band is a sensitivity, not a
confidence interval, and the screen says so.
"""

from __future__ import annotations

import math

from spectre.astro.constants import MU_EARTH

__all__ = ["position_error_km", "shift_along_track"]

_SLOW_REGIMES = frozenset({"GEO", "DEEP"})
_SECONDS_PER_DAY = 86_400.0
# (at epoch, per day of age), km
_ERROR_MODEL_KM: dict[bool, tuple[float, float]] = {False: (1.0, 2.0), True: (2.0, 1.0)}
_MEAN_ANOMALY = slice(43, 51)
_MEAN_MOTION = slice(52, 63)


def position_error_km(age_days: float, regime: str) -> float:
    """The along-track position error assumed for an element set of this age."""
    at_epoch, per_day = _ERROR_MODEL_KM[regime.strip().upper() in _SLOW_REGIMES]
    return at_epoch + per_day * max(age_days, 0.0)


def _checksum_value(c: str) -> int:
    """What one character adds to a TLE line checksum: a digit its value, a minus sign 1, anything else 0."""
    if c.isdigit():
        return int(c)
    return 1 if c == "-" else 0


def _checksum(line: str) -> int:
    return sum(_checksum_value(c) for c in line[:68]) % 10


def shift_along_track(tle: str, km: float) -> str:
    """The same element set with the object *km* further along its orbit (negative: behind).

    Moves the mean anomaly by the angle *km* subtends at the orbit's
    semi-major axis, which is exact for a circular orbit and close for the
    near-circular ones the sweep works with.
    """
    lines = [ln.rstrip() for ln in tle.strip().splitlines() if ln.strip()]
    line1, line2 = lines[-2], lines[-1].ljust(69)
    mean_motion_rad_s = float(line2[_MEAN_MOTION]) * 2.0 * math.pi / _SECONDS_PER_DAY
    sma_km = (MU_EARTH / mean_motion_rad_s ** 2) ** (1.0 / 3.0)
    anomaly = (float(line2[_MEAN_ANOMALY]) + math.degrees(km / sma_km)) % 360.0
    shifted = f"{line2[:43]}{anomaly:8.4f}{line2[51:68]}"
    shifted += str(_checksum(shifted))
    return "\n".join([*lines[:-2], line1, shifted])
