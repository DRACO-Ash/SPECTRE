"""Exercise injects: a stated burn applied to a real element set, for training only (SPC-248).

Real satellites rarely manoeuvre on cue, so a mission that needs an event applies one: a burn of stated size and
direction at a stated time, on the real object's own element set. The burned orbit is then RE-FITTED: a new element
set is fitted, at the burn time, whose SGP4 state matches the propagated state plus the burn. Every console tool reads
element sets, so a fitted set is what lets every one of them, and every mission quantity, use the injected orbit.

The fit runs on equinoctial elements, which stay defined for the near-circular, near-equatorial orbits of the
geostationary belt where the classical node and perigee do not. It starts from the burned state's osculating elements
and corrects them by the difference between the target state and the fitted set's own SGP4 state at its epoch, until
that difference stops shrinking; the residual is measured on the set as written, rounded to the element set's own
columns, and a fit worse than FIT_LIMIT_KM is refused rather than used.

The burn is given in the object's RSW frame at the burn time: radial (away from the Earth), along-track (in the orbit
plane, perpendicular to radial, in the direction of motion), cross-track (along the orbit normal), in m/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sgp4.api import WGS72, Satrec, jday

from spectre.astro.propagator import TLEOrbit

#: The gravitational parameter SGP4's WGS-72 constants use, km^3/s^2: the fit compares SGP4 states, so it uses SGP4's.
_MU = 398600.8
#: The largest position residual, km, at which a fitted set is accepted. The fit itself converges to millimetres;
#: what is left is the rounding of the element set's own columns (angles to 1e-4 degrees, about 74 m at the
#: geostationary radius), measured at tens of metres on the belt's near-equatorial sets.
FIT_LIMIT_KM = 0.05
_ITERATIONS = 30
#: The finite-difference steps of the fit, per equinoctial element (mean motion in rad/s, then h, k, p, q and the
#: mean longitude in radians).
_STEPS = np.array([1e-12, 1e-7, 1e-7, 1e-7, 1e-7, 1e-7])
#: The Julian date SGP4 counts its epoch from, 31 December 1949 00:00 UTC.
_SGP4_EPOCH_JD = 2433281.5
_SECONDS_PER_DAY = 86400.0
_TLE_LINE_LENGTH = 69


class InjectError(ValueError):
    """The burn could not be applied: the set did not propagate, or no set could be fitted to the burned orbit."""


@dataclass(frozen=True)
class Injected:
    """The fitted element set, when it holds, and how closely it reproduces the burned state."""

    tle: str
    epoch: datetime
    residual_km: float
    burn_m_s: tuple[float, float, float]



#: The fit has converged when every element's step is under a thousandth of its finite-difference step.
_CONVERGED = 1e-3
#: An element set is two lines.
_TLE_LINES = 2

def rsw_burn(r: np.ndarray, v: np.ndarray, burn_m_s: tuple[float, float, float]) -> np.ndarray:
    """The velocity change, km/s in the state's own frame, of a burn given as radial, along-track, cross-track m/s."""
    radial = r / np.linalg.norm(r)
    normal = np.cross(r, v)
    normal = normal / np.linalg.norm(normal)
    along = np.cross(normal, radial)
    dv = burn_m_s[0] * radial + burn_m_s[1] * along + burn_m_s[2] * normal
    return np.asarray(dv / 1000.0, dtype=float)


def _equinoctial(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Mean motion (rad/s), h, k, p, q and mean longitude (rad) of the osculating orbit of state (r, v)."""
    rmag = float(np.linalg.norm(r))
    a = 1.0 / (2.0 / rmag - float(np.dot(v, v)) / _MU)
    e_vec = ((float(np.dot(v, v)) - _MU / rmag) * r - float(np.dot(r, v)) * v) / _MU
    w = np.cross(r, v)
    w = w / np.linalg.norm(w)
    p = w[0] / (1.0 + w[2])
    q = -w[1] / (1.0 + w[2])
    scale = 1.0 + p * p + q * q
    f_hat = np.array([1.0 - p * p + q * q, 2.0 * p * q, -2.0 * p]) / scale
    g_hat = np.array([2.0 * p * q, 1.0 + p * p - q * q, 2.0 * q]) / scale
    k = float(np.dot(e_vec, f_hat))
    h = float(np.dot(e_vec, g_hat))
    true_longitude = math.atan2(float(np.dot(r, g_hat)), float(np.dot(r, f_hat)))
    ecc = math.hypot(h, k)
    perigee_longitude = math.atan2(h, k)
    nu = true_longitude - perigee_longitude
    ecc_anomaly = 2.0 * math.atan2(math.sqrt(1.0 - ecc) * math.sin(nu / 2.0), math.sqrt(1.0 + ecc) * math.cos(nu / 2.0))
    mean_longitude = ecc_anomaly - ecc * math.sin(ecc_anomaly) + perigee_longitude
    return np.array([math.sqrt(_MU / a ** 3), h, k, p, q, mean_longitude])


def _classical(eq: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """Mean motion (rev/day), eccentricity, inclination, node, argument of perigee and mean anomaly (degrees)."""
    n, h, k, p, q, mean_longitude = (float(x) for x in eq)
    ecc = math.hypot(h, k)
    node = math.atan2(p, q)
    inc_rad = 2.0 * math.atan(math.hypot(p, q))
    perigee_longitude = math.atan2(h, k)
    return (
        n * _SECONDS_PER_DAY / (2.0 * math.pi),
        ecc,
        math.degrees(inc_rad),
        math.degrees(node) % 360.0,
        math.degrees(perigee_longitude - node) % 360.0,
        math.degrees(mean_longitude - perigee_longitude) % 360.0,
    )


def _checksum(line: str) -> str:
    total = sum(int(c) if c.isdigit() else int(c == "-") for c in line[:68])
    return str(total % 10)


def _epoch_field(epoch: datetime) -> str:
    start = datetime(epoch.year, 1, 1, tzinfo=UTC)
    day = 1.0 + (epoch - start).total_seconds() / _SECONDS_PER_DAY
    return f"{epoch.year % 100:02d}{day:012.8f}"


def _lines(template: TLEOrbit, epoch: datetime, elements: tuple[float, float, float, float, float, float]) -> str:
    """The element set written in TLE columns: the template's number and designator, zero drag terms, *elements*."""
    n_rev_day, ecc, inc, node, argp, mean_anomaly = elements
    line1 = (f"{template.line1[:18]}{_epoch_field(epoch)}  .00000000  00000-0  00000-0 0  999")
    line1 = line1[:68] + _checksum(line1)
    satno = template.line2[2:7]
    ecc_text = f"{min(ecc, 0.9999999):.7f}"[2:]
    line2 = (f"2 {satno} {inc:8.4f} {node:8.4f} {ecc_text} {argp:8.4f} {mean_anomaly:8.4f} "
             f"{n_rev_day:11.8f}{template.line2[63:68]}")
    line2 = line2[:68] + _checksum(line2.ljust(68))
    return f"{line1}\n{line2}"


def _state(tle: str, epoch: datetime) -> np.ndarray:
    sv = TLEOrbit(tle).propagate(epoch)
    return np.concatenate([sv.r, sv.v])


def _wrapped(delta: np.ndarray) -> np.ndarray:
    delta = delta.copy()
    delta[5] = (delta[5] + math.pi) % (2.0 * math.pi) - math.pi
    return delta


def _model_state(eq: np.ndarray, epoch: datetime, satnum: int) -> np.ndarray:
    """The osculating equinoctial elements of SGP4's state at *epoch* for the mean elements *eq*, unrounded."""
    n_rev_day, ecc, inc, node, argp, mean_anomaly = _classical(eq)
    jd, fr = jday(epoch.year, epoch.month, epoch.day, epoch.hour, epoch.minute, epoch.second)
    sat = Satrec()
    sat.sgp4init(WGS72, "i", satnum, jd + fr - _SGP4_EPOCH_JD, 0.0, 0.0, 0.0, ecc, math.radians(argp),
                 math.radians(inc), math.radians(mean_anomaly), n_rev_day * 2.0 * math.pi / 1440.0,
                 math.radians(node))
    _, r, v = sat.sgp4(jd, fr)
    return _equinoctial(np.array(r), np.array(v))


def _newton(wanted: np.ndarray, epoch: datetime, satnum: int) -> np.ndarray:
    """Mean equinoctial elements whose SGP4 osculating elements at *epoch* are *wanted*: Newton's method on a
    finite-difference Jacobian. Correcting by the difference alone stalled kilometres out on a near-equatorial set."""
    guess = wanted.copy()
    for _ in range(_ITERATIONS):
        residual = _wrapped(_model_state(guess, epoch, satnum) - wanted)
        if np.all(np.abs(residual / _STEPS) < _CONVERGED):
            break
        jacobian = np.empty((6, 6))
        for j in range(6):
            nudged = guess.copy()
            nudged[j] += _STEPS[j]
            jacobian[:, j] = _wrapped(_model_state(nudged, epoch, satnum) - wanted - residual) / _STEPS[j]
        guess = guess - np.linalg.solve(jacobian, residual)
    return guess


def fit_element_set(template_tle: str, epoch: datetime, target: np.ndarray) -> tuple[str, float]:
    """An element set at *epoch* whose SGP4 state there matches *target* (r km, v km/s), and its residual in km,
    measured on the set as written in its columns."""
    template = TLEOrbit(template_tle)
    satnum = int(template.line2[2:7]) if template.line2[2:7].strip().isnumeric() else 0
    elements = _newton(_equinoctial(target[:3], target[3:]), epoch, satnum)
    tle = _lines(template, epoch, _classical(elements))
    return tle, float(np.linalg.norm(_state(tle, epoch)[:3] - target[:3]))


def inject(tle: str, at: datetime, burn_m_s: tuple[float, float, float]) -> Injected:
    """Apply *burn_m_s* (radial, along-track, cross-track) to *tle* at *at* and fit the burned orbit's element set.

    Raises InjectError when the set does not propagate to *at*, or no fit comes within FIT_LIMIT_KM.
    """
    at = at.astimezone(UTC).replace(microsecond=0)
    try:
        sv = TLEOrbit(tle).propagate(at)
    except (RuntimeError, ValueError) as exc:
        raise InjectError(f"the element set does not propagate to {at:%Y-%m-%d %H:%M} UTC") from exc
    burned = np.concatenate([sv.r, sv.v + rsw_burn(sv.r, sv.v, burn_m_s)])
    fitted, residual = fit_element_set(tle, at, burned)
    if residual > FIT_LIMIT_KM:
        raise InjectError(f"no element set fits the burned orbit within {FIT_LIMIT_KM} km (best {residual:.2f} km)")
    return Injected(fitted, at, residual, burn_m_s)


def inject_time(clock: datetime, at: str) -> datetime:
    """The burn time an inject's *at* names: "start", the mission clock, the only time handled so far.

    A later burn would need the set before the burn until then and the fitted set after it, and every console tool
    takes one set per object, so it is refused at load (valid_at) until that is handled.
    """
    if not valid_at(at):
        raise InjectError(f"an inject at {at!r} is not handled: only start is")
    return clock


def valid_at(at: str) -> bool:
    """Whether *at* is a burn time the inject handles: "start"."""
    return at == "start"


def satrec_ok(tle: str) -> bool:
    """Whether SGP4 starts on *tle* without an error."""
    lines = tle.splitlines()
    return len(lines) == _TLE_LINES and Satrec.twoline2rv(lines[0], lines[1]).error == 0
