"""Hand-checked closest-approach reference cases for the Decision Engine (SPC-102).

Three pairs of circular orbits, each with a miss distance and a time of
closest approach (TCA) worked out in closed form and checked by a fixed-step
RK4 two-body integration below. SPC-110 and SPC-120 must reproduce them
through their own paths (tests/unit/test_decision_reference_cases.py).

The values here must never come from the code under test, so this module
imports only the standard library and numpy: no spectre, sgp4 or scipy. The
constants are typed as literals for the same reason (they are the values
spectre/astro/constants.py cites).

All orbits are circular, with eccentricity 0 and argument of perigee 0, so
the mean anomaly in each element set is the argument of latitude u. The mean
motion written into each element set is the two-body n from a. SGP4 reads it
as a Kozai mean element, which is why each case is built so the
mean-to-osculating offsets are common to both objects.

Measured gaps, so a reviewer can see the headroom (sgp4 2.27, numpy 2.4.6,
scipy 1.17.1; J2 is RK45 from the SGP4 state at epoch, rtol 1e-8):

* coplanar_leo: closed form 10.000 km at 14,488.1 s. SGP4 10.0055 km at
  14,483.96 s (+0.005 km, -4.2 s, against 0.10 km and 15 s); J2 10.0057 km
  at 14,484.12 s; RK4 at 5 s 10.00000 km at 14,488.149 s.
* geo_drift_in: closed form 30.000 km at 112,031.1 s. SGP4, deep-space
  branch, 29.9991 km at 112,016.27 s (-0.001 km, -14.8 s, against 0.10 km
  and 60 s); J2 30.0001 km at 112,015.23 s; RK4 at 60 s 30.00000 km at
  112,031.061 s.
* plane_change: closed form 10.453 km at 1,410.0 s. SGP4 10.4036 km at
  1,410.93 s (-0.049 km, +0.9 s, against 0.15 km and 5 s); J2 10.4036 km at
  1,410.93 s; RK4 at 1 s 10.45276 km at 1,410.039 s. The next crossing,
  4,279.5 s in two-body and 4,282 s at 10.582 km under SGP4 (a 0.129 km
  gap), lies outside the 1 h horizon on purpose.

Re-measure every gap on any sgp4 upgrade, and on any change to a case's
horizon or phases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

#: The items whose paths must pass the gate before they are done.
GATED_ITEMS: tuple[str, ...] = ("SPC-110", "SPC-120")

EPOCH = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EPOCH_DAY = "26290.50000000"

MU_KM3_S2 = 398600.4418
RE_KM = 6378.137
SIDEREAL_DAY_S = 86164.0905

#: The second window start, in seconds after epoch, the gate runs every path at.
ORIGIN_OFFSET_S = 600.0

_SECONDS_PER_DAY = 86400.0
_TWO_PI = 2.0 * math.pi
_HOUR_S = 3600.0
#: The geostationary radius, from the sidereal day (42,164.170 km).
_GEO_A_KM = (MU_KM3_S2 * (SIDEREAL_DAY_S / _TWO_PI) ** 2) ** (1.0 / 3.0)


@dataclass(frozen=True)
class Circular:
    """A circular orbit: semi-major axis, inclination, RAAN and argument of latitude."""

    satno: int
    a_km: float
    inc_deg: float
    raan_deg: float
    u_deg: float


def mean_motion_rad_s(body: Circular) -> float:
    """The two-body mean motion sqrt(mu / a^3)."""
    return math.sqrt(MU_KM3_S2 / body.a_km**3)


def mean_motion_rev_day(body: Circular) -> float:
    """The two-body mean motion in revolutions per day, as an element set carries it."""
    return mean_motion_rad_s(body) * _SECONDS_PER_DAY / _TWO_PI


def _checksum(line: str) -> str:
    """Modulo-10 sum of the first 68 columns: digits count their value, a minus sign 1."""
    return str(sum(int(c) if c.isdigit() else int(c == "-") for c in line) % 10)


def element_set(body: Circular, epoch_day: str = EPOCH_DAY) -> str:
    """The two-line element set for *body*, both lines 69 columns with computed checksums."""
    line1 = f"1 {body.satno:05d}U 26001A   {epoch_day}  .00000000  00000-0  00000-0 0  999"
    line2 = (
        f"2 {body.satno:05d} {body.inc_deg:8.4f} {body.raan_deg:8.4f} 0000000 {0.0:8.4f} "
        f"{body.u_deg:8.4f} {mean_motion_rev_day(body):11.8f}{1:5d}"
    )
    return f"{line1}{_checksum(line1)}\n{line2}{_checksum(line2)}"


@dataclass(frozen=True)
class ReferenceCase:
    """Two orbits, the hand-checked miss and TCA, and the tolerances a path must meet."""

    name: str
    title: str
    blue: Circular
    red: Circular
    horizon_s: float
    step_s: float
    rk4_dt_s: float
    miss_km: float
    tca_s: float
    miss_tol_km: float
    tca_tol_s: float

    @property
    def blue_tle(self) -> str:
        return element_set(self.blue)

    @property
    def red_tle(self) -> str:
        return element_set(self.red)

    @property
    def horizon_hours(self) -> float:
        return self.horizon_s / _HOUR_S


def coplanar_closed_form(blue: Circular, red: Circular) -> tuple[float, float]:
    """(miss km, TCA s) for two circular orbits in one plane.

    The miss is the difference in radius. The TCA is the first t > 0 at which
    u_red - u_blue reaches a multiple of 2 pi.
    """
    phase = math.radians(red.u_deg - blue.u_deg)
    drift = mean_motion_rad_s(red) - mean_motion_rad_s(blue)
    to_go = (-phase) % _TWO_PI if drift > 0.0 else phase % _TWO_PI
    return abs(red.a_km - blue.a_km), (to_go or _TWO_PI) / abs(drift)


def _unit_normal(body: Circular) -> np.ndarray:
    i, raan = math.radians(body.inc_deg), math.radians(body.raan_deg)
    return np.array([math.sin(i) * math.sin(raan), -math.sin(i) * math.cos(raan), math.cos(i)])


def _node(body: Circular) -> np.ndarray:
    raan = math.radians(body.raan_deg)
    return np.array([math.cos(raan), math.sin(raan), 0.0])


def _latitude_argument(body: Circular, direction: np.ndarray) -> float:
    """The argument of latitude, in radians, of *direction* in the plane of *body*."""
    node = _node(body)
    ahead = np.cross(_unit_normal(body), node)
    return math.atan2(float(direction @ ahead), float(direction @ node))


def crossing_closed_form(blue: Circular, red: Circular) -> tuple[float, float]:
    """(miss km, TCA s) for two circular orbits of equal radius in crossing planes.

    With g the mutual inclination and x1, x2 each body's angle past the line
    of nodes x = h1 x h2, the angle between the position vectors satisfies
    cos theta = cos d cos^2(g/2) + cos 2s sin^2(g/2), where d = x2 - x1 is
    fixed and s = (x1 + x2) / 2 advances at the mean motion. The smallest
    angle is at s = 0 mod pi.
    """
    h1, h2 = _unit_normal(blue), _unit_normal(red)
    g = math.acos(float(np.clip(h1 @ h2, -1.0, 1.0)))
    line = np.cross(h1, h2)
    line /= np.linalg.norm(line)
    x1 = math.radians(blue.u_deg) - _latitude_argument(blue, line)
    x2 = math.radians(red.u_deg) - _latitude_argument(red, line)
    d, s = x2 - x1, (x1 + x2) / 2.0
    cos_theta = math.cos(d) * math.cos(g / 2.0) ** 2 + math.sin(g / 2.0) ** 2
    miss = blue.a_km * math.sqrt(2.0 * (1.0 - cos_theta))
    return miss, ((-s) % math.pi) / mean_motion_rad_s(blue)


def _circular_state(body: Circular) -> np.ndarray:
    u = math.radians(body.u_deg)
    node, ahead = _node(body), np.cross(_unit_normal(body), _node(body))
    speed = math.sqrt(MU_KM3_S2 / body.a_km)
    r = body.a_km * (math.cos(u) * node + math.sin(u) * ahead)
    v = speed * (-math.sin(u) * node + math.cos(u) * ahead)
    return np.concatenate([r, v])


def _derivative(states: np.ndarray) -> np.ndarray:
    r = states[:, :3]
    accel = -MU_KM3_S2 * r / np.linalg.norm(r, axis=1, keepdims=True) ** 3
    return np.hstack([states[:, 3:], accel])


_SERIES: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def two_body_separation(case: ReferenceCase) -> tuple[np.ndarray, np.ndarray]:
    """(times s, separations km) from a fixed-step RK4 point-mass integration.

    Both bodies start from their circular state at u, and step together at
    case.rk4_dt_s across the horizon. Cached per case.
    """
    if case.name not in _SERIES:
        dt = case.rk4_dt_s
        steps = round(case.horizon_s / dt)
        states = np.vstack([_circular_state(case.blue), _circular_state(case.red)])
        seps = np.empty(steps + 1)
        seps[0] = np.linalg.norm(states[0, :3] - states[1, :3])
        for k in range(1, steps + 1):
            k1 = _derivative(states)
            k2 = _derivative(states + 0.5 * dt * k1)
            k3 = _derivative(states + 0.5 * dt * k2)
            k4 = _derivative(states + dt * k3)
            states = states + dt / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
            seps[k] = np.linalg.norm(states[0, :3] - states[1, :3])
        _SERIES[case.name] = (np.arange(steps + 1) * dt, seps)
    return _SERIES[case.name]


def parabolic_minimum(times: np.ndarray, seps: np.ndarray) -> tuple[float, float]:
    """(separation km, t s) at the vertex of the parabola through the smallest sample and its neighbours."""
    k = int(np.argmin(seps))
    k = min(max(k, 1), len(seps) - 2)
    t1, h = times[k], times[k] - times[k - 1]
    y0, y1, y2 = seps[k - 1 : k + 2]
    curvature = y0 - 2.0 * y1 + y2
    t = t1 + h * (y0 - y2) / (2.0 * curvature)
    return float(y1 - (y0 - y2) ** 2 / (8.0 * curvature)), float(t)


COPLANAR_LEO = ReferenceCase(
    name="coplanar_leo",
    title="Co-planar LEO, red parked 10 km above, blue passes beneath",
    blue=Circular(90001, RE_KM + 500.0, 51.6, 40.0, 0.0),
    red=Circular(90002, RE_KM + 510.0, 51.6, 40.0, 2.0),
    horizon_s=6 * _HOUR_S,
    step_s=60.0,
    rk4_dt_s=5.0,
    miss_km=10.000,
    tca_s=14488.1,
    miss_tol_km=0.10,
    tca_tol_s=15.0,
)

GEO_DRIFT_IN = ReferenceCase(
    name="geo_drift_in",
    title="GEO drift-in, red 30 km below and 0.5 deg west, drifting east at 0.386 deg/day",
    blue=Circular(90001, _GEO_A_KM, 0.05, 80.0, 100.0),
    red=Circular(90002, _GEO_A_KM - 30.0, 0.05, 80.0, 99.5),
    horizon_s=48 * _HOUR_S,
    step_s=300.0,
    rk4_dt_s=60.0,
    miss_km=30.000,
    tca_s=112031.1,
    miss_tol_km=0.10,
    tca_tol_s=60.0,
)

PLANE_CHANGE = ReferenceCase(
    name="plane_change",
    title="Plane change: red's plane 3 deg of RAAN from blue's, crossing near the pole",
    blue=Circular(90001, RE_KM + 550.0, 97.4, 40.0, 1.4),
    red=Circular(90002, RE_KM + 550.0, 97.4, 43.0, 1.7),
    horizon_s=1 * _HOUR_S,
    step_s=60.0,
    rk4_dt_s=1.0,
    miss_km=10.453,
    tca_s=1410.0,
    miss_tol_km=0.15,
    tca_tol_s=5.0,
)

REFERENCE_CASES: tuple[ReferenceCase, ...] = (COPLANAR_LEO, GEO_DRIFT_IN, PLANE_CHANGE)
