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

Every element set is stated in its regime where this rate and the staleness
limit are applied (SPC-215, evaluation F-29): LEO, MEO, HEO/Molniya, GEO or
other deep-space, by its period and eccentricity (orbit_regime). Neither the
rate nor the limit could be sourced for any regime, so each set keeps the
figure it had, LEO's or GEO's, chosen as before by the regime family
propagator.regime_from_tle reads; where that is another regime's figure the
statement says "LEO figure applied to <regime>, unsourced for this regime".
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from spectre.astro.constants import (
    _HEO_MIN_ECC,
    _LEO_MAX_ALT,
    _MEO_MAX_ALT,
    MU_EARTH,
    R_EARTH,
    SIDEREAL_DAY,
)
from spectre.astro.propagator import DEEP_SPACE_PERIOD_MIN, TLE_ERRORS, TLEOrbit, regime_from_tle

__all__ = [
    "ERROR_MODEL_WORDS",
    "RegimeBasis",
    "error_rate_words",
    "figure_applied",
    "orbit_regime",
    "position_error_km",
    "regime_basis",
    "shift_along_track",
]

#: The regimes an element set is stated in (SPC-215).
LEO, MEO, HEO, GEO, OTHER_DEEP = "LEO", "MEO", "HEO/Molniya", "GEO", "other deep-space"
_SECONDS_PER_MINUTE = 60.0
#: The geosynchronous period, min: the sidereal day.
GEO_PERIOD_MIN = SIDEREAL_DAY / _SECONDS_PER_MINUTE
#: A period this close to it, min, with an eccentricity under 0.25, is stated GEO whatever its apsides (V0.40 review):
#: just wider than the periods of circular orbits at the GEO altitude band's edges, 400 km either side (20.4 min), so
#: a circular orbit is never left between GEO and MEO. Unsourced judgement, in docs/lookup-register.md.
GEO_PERIOD_BAND_MIN = 20.5

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


def orbit_regime(period_min: float, eccentricity: float) -> str:
    """The regime an orbit is stated in, from its period, minutes, and eccentricity (SPC-215).

    HEO/Molniya at an eccentricity of 0.25 or more, whatever the period; GEO for a period within GEO_PERIOD_BAND_MIN
    of the sidereal day, whatever the apsides; otherwise by the apsides the period and eccentricity give (_by_apsides).
    Raises ValueError for a period or eccentricity that is not a finite orbit's: no regime is guessed.

    It can differ from constants.classify_orbit_regime, which chooses the figure applied and is left as it was so
    that no limit or rate moves: that reads a geosynchronous set of e about 0.0095 or more as MEO, and the statement
    then says the LEO figure is applied to GEO, unsourced for this regime.
    """
    if not (math.isfinite(period_min) and period_min > 0.0 and 0.0 <= eccentricity < 1.0):
        raise ValueError(f"no regime for a period of {period_min!r} min and an eccentricity of {eccentricity!r}")
    if eccentricity >= _HEO_MIN_ECC:
        return HEO
    if abs(period_min - GEO_PERIOD_MIN) <= GEO_PERIOD_BAND_MIN:
        return GEO
    a = (MU_EARTH * (period_min * _SECONDS_PER_MINUTE / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)
    return _by_apsides(a * (1.0 - eccentricity) - R_EARTH, a * (1.0 + eccentricity) - R_EARTH, period_min)


def _by_apsides(perigee_km: float, apogee_km: float, period_min: float) -> str:
    """The regime of a low-eccentricity orbit off the GEO period, by its apsides' altitudes against the bands
    spectre.astro.constants draws: LEO with its apogee under 2,000 km, MEO with its perigee at or over 2,000 km and
    its apogee under the GEO band's lower edge; anything else other deep-space at SGP4's deep-space period or over,
    and LEO under it (a near-Earth orbit crossing 2,000 km, too short a period to be anything else)."""
    if apogee_km < _LEO_MAX_ALT:
        return LEO
    if perigee_km >= _LEO_MAX_ALT and apogee_km < _MEO_MAX_ALT:
        return MEO
    return OTHER_DEEP if period_min >= DEEP_SPACE_PERIOD_MIN else LEO


@dataclass(frozen=True)
class RegimeBasis:
    """An element set's regime, and whose figure its staleness limit and error rate are (SPC-215).

    *figure* is "LEO" or "GEO": the regime the figure applied was set for, chosen as it always was, by the regime
    family propagator.regime_from_tle reads, GEO's for GEO and beyond the GEO band and LEO's for everything else.
    """

    regime: str
    figure: str
    period_min: float
    eccentricity: float

    @property
    def applied(self) -> str:
        """Whose figure is applied, and, where it is another regime's, that it is unsourced for this one."""
        if self.figure == self.regime:
            return f"{self.figure} figure, set for {self.regime}"
        return f"{self.figure} figure applied to {self.regime}, unsourced for this regime"

    @property
    def line(self) -> str:
        """The statement in a sentence: the regime, what it was read from, and whose figure is applied."""
        return f"Regime {self.regime} (period {self.period_min:.0f} min, e {self.eccentricity:.3f}): {self.applied}."


def regime_basis(tle: str) -> RegimeBasis | None:
    """*tle*'s regime and the figure applied to it; None when the set cannot be read."""
    try:
        orbit = TLEOrbit(tle)
        family = regime_from_tle(tle)
        period, ecc = orbit.period_minutes, orbit.eccentricity
        regime = orbit_regime(period, ecc)
    except TLE_ERRORS:
        return None
    figure = GEO if family.strip().upper() in _SLOW_REGIMES else LEO
    return RegimeBasis(regime, figure, period, ecc)


def figure_applied(tle: str, family: str | None = None) -> str:
    """Whose figure is applied to *tle*, in words ("LEO figure applied to HEO/Molniya, unsourced for this regime"),
    for beside a staleness limit or an error rate; "" when its regime cannot be read. *family* is the regime family
    the caller chose the figure by, when it is not the set's own (regime_from_tle)."""
    basis = regime_basis(tle)
    if basis is None:
        return ""
    if family is not None:
        basis = dataclasses.replace(basis, figure=GEO if family.strip().upper() in _SLOW_REGIMES else LEO)
    return basis.applied


#: The error model in words, tied to whose figure a set takes rather than to a regime it may not be in (V0.40 review).
ERROR_MODEL_WORDS = (
    "1 km at epoch plus 2 km a day by the LEO figure and 2 km plus 1 km a day by the GEO figure; a set read as GEO, "
    "or with its perigee beyond the GEO band, takes GEO's, and every other set LEO's, MEO and HEO/Molniya included, "
    "as each set's regime line says"
)


def error_rate_words(tle: str) -> str:
    """The error rate applied to *tle*, in words with its regime basis: "1 km plus 2 km a day, LEO figure, ...".

    Where the regime cannot be read the rate is still the one applied, chosen by regime_from_tle, or LEO's, the
    stricter, when that cannot be read either, and the words say the regime is not readable."""
    basis = regime_basis(tle)
    if basis is not None:
        slow = basis.figure == GEO
    else:
        try:
            slow = regime_from_tle(tle).strip().upper() in _SLOW_REGIMES
        except TLE_ERRORS:
            slow = False
    at_epoch, per_day = _ERROR_MODEL_KM[slow]
    rate = f"{at_epoch:g} km plus {per_day:g} km a day"
    return f"{rate}, {basis.applied}" if basis is not None else f"{rate}, regime not readable"


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
