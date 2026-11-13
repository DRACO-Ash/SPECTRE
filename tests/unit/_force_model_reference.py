"""A higher-fidelity force model, for measurement only (SPC-209, evaluation F-19). Nothing in spectre imports it.

The engine's RK45 flies two-body, J2 and exponential drag (spectre.astro.monte_carlo._j2_drag_ode). This module adds
what that omits, so tests/unit/test_force_model_error.py can measure what the omission moves, by regime and by burn
size. It lives under tests/, beside the hand-checked reference cases, because it is a measuring instrument: it is not
shipped, it adds no dependency (numpy and scipy only), and it never stands in the product path.

Forces, each switched on or off by Forces:

● two-body and J2 exactly as the engine computes them, from spectre.astro.monte_carlo's own constants;
● J3 and J4, the EGM-96 zonal coefficients unnormalised (Lemoine and others, NASA/TP-1998-206861, 1998), to the 5
  figures commonly tabulated; the accelerations are the gradient of the zonal potential, which
  tests/unit/test_force_model_error.py checks against a numerical gradient of mu / r (R / r)^n Jn Pn(z / r);
● the Moon and the Sun as point masses: the Moon from the low-precision analytic series of Montenbruck and Gill,
  Satellite Orbits (Springer, 2000), section 3.3.2, and the Sun from Meeus, Astronomical Algorithms (2nd ed., 1998),
  chapter 25, low accuracy, both referred to the mean equator and equinox of date. SGP4's TEME frame is the true
  equator of date with a mean equinox, so it differs from that frame by nutation, at most about 20 arcseconds (about
  17 in longitude and 9 in obliquity), under 0.0001 rad: it turns each body's direction by that much, which is
  negligible beside what is measured here and is not corrected. GM of the Sun and the Moon-to-Earth mass ratio from
  the IERS Conventions (2010), IERS Technical Note 36, Table 1.1;
● solar radiation pressure as a cannonball, 4.56e-6 N/m^2 at 1 au (Montenbruck and Gill, section 3.4: the solar flux
  of about 1,367 W/m^2 over the speed of light), scaled by the inverse square of the distance from the Sun, in a
  cylindrical Earth shadow whose edge is smoothed so the integrator can follow it (SHADOW_EDGE_KM); Cr and the
  area-to-mass ratio are per object, and the defaults are a judgement, not sourced (SRP_CR, SRP_AREA_TO_MASS_M2_KG);
● drag exactly as the engine computes it: Vallado's exponential atmosphere, the ballistic coefficient from B*, the
  atmosphere not rotating, and nothing above 800 km.

Time: the series take Terrestrial Time; it is UTC plus 69.184 s here (37 leap seconds since 2017, plus 32.184 s).
tests/unit/test_force_model_error.py checks both series against worked examples and dated events before any figure
is measured.

Every object of a run is integrated in one state vector, so an ensemble costs one call to solve_ivp, not one per
sample.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo

#: Astronomical unit, km (IAU 2012 Resolution B2).
AU_KM = 149_597_870.7
#: GM of the Sun, km^3/s^2 (IERS Conventions 2010, Table 1.1: 1.32712442099e20 m^3/s^2).
GM_SUN = 1.32712442099e11
#: GM of the Moon, km^3/s^2: the Moon-to-Earth mass ratio 0.0123000371 (IERS Conventions 2010, Table 1.1) times the
#: engine's own Earth GM.
GM_MOON = 0.0123000371 * monte_carlo._MU
#: EGM-96 J3 and J4, unnormalised, 5 figures (NASA/TP-1998-206861).
J3 = -2.5327e-6
J4 = -1.6196e-6
#: Solar radiation pressure at 1 au, N/m^2 (Montenbruck and Gill, section 3.4).
P_SUN_N_M2 = 4.56e-6
#: How far either side of the shadow's edge the light is smoothed, km. A sharp edge switches the force on and off in
#: a step DOP853 cannot follow: measured, it left about 0.035 km of integration error in a LEO orbit and 0.045 km in
#: a Molniya orbit by 72 h, tolerance 1e-11 against 1e-13, where this edge leaves under 0.001 km and moves radiation
#: pressure's own effect by under 5 per cent (0.101 against 0.105 km, 1.646 against 1.655 km). A judgement.
SHADOW_EDGE_KM = 300.0
#: The radiation pressure coefficient and area-to-mass ratio, m^2/kg, each object is given unless told otherwise.
#: A judgement, not sourced: a box-wing satellite with its panels, at the upper end of what such objects carry, and
#: far above the 5.8e-4 m^2/kg that B* 1e-4 implies at a drag coefficient of 2.2, so the measurement does not
#: understate radiation pressure.
SRP_CR = 1.3
SRP_AREA_TO_MASS_M2_KG = 0.02
#: TT less UTC, s, from 2017 on.
TT_MINUS_UTC_S = 69.184
_J2000_JD = 2451545.0
_JULIAN_CENTURY_DAYS = 36525.0
_UNIX_EPOCH_JD = 2440587.5
_DAY_S = 86400.0
_ARCSEC = math.pi / (180.0 * 3600.0)
_DEG = math.pi / 180.0
# The engine switches drag off above this altitude, km, and below this speed, km/s (monte_carlo._j2_drag_ode).
_DRAG_CEILING_KM = 800.0
_DRAG_MIN_SPEED_KM_S = 0.01
_ATMOSPHERE = np.array(monte_carlo._EXPONENTIAL_ATMOSPHERE)
# The engine's forces read no clock; flown_for passes this where acceleration asks for an epoch.
_NO_EPOCH = datetime(2000, 1, 1, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Forces:
    """Which forces the reference adds to two-body, J2 and drag. All off is the engine's own model."""

    j3_j4: bool = True
    moon: bool = True
    sun: bool = True
    srp: bool = True


#: The engine's own force model, and the reference's full one.
OPERATIONAL = Forces(j3_j4=False, moon=False, sun=False, srp=False)
FULL = Forces()


def centuries_tt(at: datetime) -> float:
    """Julian centuries of TT since J2000 at *at* (UTC)."""
    jd_utc = _UNIX_EPOCH_JD + at.timestamp() / _DAY_S
    return (jd_utc + TT_MINUS_UTC_S / _DAY_S - _J2000_JD) / _JULIAN_CENTURY_DAYS


def _obliquity_rad(t: float) -> float:
    """Mean obliquity of the ecliptic of date, rad: 23.43929111 degrees less 46.8150 arcseconds a century."""
    return (23.43929111 - 46.8150 / 3600.0 * t) * _DEG


def _equatorial(longitude: float, latitude: float, distance: float, t: float) -> np.ndarray:
    eps = _obliquity_rad(t)
    x = distance * math.cos(longitude) * math.cos(latitude)
    y = distance * math.sin(longitude) * math.cos(latitude)
    z = distance * math.sin(latitude)
    return np.array([x, y * math.cos(eps) - z * math.sin(eps), y * math.sin(eps) + z * math.cos(eps)])


def sun_ecliptic(t: float) -> tuple[float, float, float]:
    """The Sun's geometric ecliptic longitude and latitude, rad, and distance, km, of date, at *t* Julian centuries of
    TT since J2000: Meeus, Astronomical Algorithms (2nd ed., Willmann-Bell, 1998), chapter 25, the low-accuracy
    method, which Meeus gives as accurate to 0.01 degree. Montenbruck and Gill's solar series holds the longitude of
    perigee fixed, so it drifts about 0.3 degree a century from 2000 and was 0.08 degree out at the 2026 equinoxes;
    Meeus's carries its motion."""
    mean_longitude = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) * _DEG
    e = 0.016708634 - 0.000042037 * t - 0.0000001267 * t * t
    centre = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m) + (0.019993 - 0.000101 * t) * math.sin(2.0 * m)
        + 0.000289 * math.sin(3.0 * m)
    ) * _DEG
    distance_au = 1.000001018 * (1.0 - e * e) / (1.0 + e * math.cos(m + centre))
    return mean_longitude * _DEG + centre, 0.0, distance_au * AU_KM


def moon_ecliptic(t: float) -> tuple[float, float, float]:
    """The Moon's geocentric ecliptic longitude and latitude, rad, and distance, km, of date (Montenbruck and Gill,
    section 3.3.2), at *t* Julian centuries of TT since J2000. Their mean longitude carries -1.3972 degrees a century
    to refer it to J2000; that term is left out here, so the longitude is of date, as the Sun's is."""
    l0 = (218.31617 + 481267.88088 * t) * _DEG
    l = (134.96292 + 477198.86753 * t) * _DEG  # noqa: E741  (the series' own name, the Moon's mean anomaly)
    lp = (357.52543 + 35999.04944 * t) * _DEG
    f = (93.27283 + 483202.01873 * t) * _DEG
    d = (297.85027 + 445267.11135 * t) * _DEG
    s = math.sin
    perturbation = (
        22640 * s(l) + 769 * s(2 * l) - 4586 * s(l - 2 * d) + 2370 * s(2 * d) - 668 * s(lp) - 412 * s(2 * f)
        - 212 * s(2 * l - 2 * d) - 206 * s(l + lp - 2 * d) + 192 * s(l + 2 * d) - 165 * s(lp - 2 * d)
        + 148 * s(l - lp) - 125 * s(d) - 110 * s(l + lp) - 55 * s(2 * f - 2 * d)
    ) * _ARCSEC
    longitude = l0 + perturbation
    latitude = (
        18520 * s(f + perturbation + (412 * s(2 * f) + 541 * s(lp)) * _ARCSEC) - 526 * s(f - 2 * d)
        + 44 * s(l + f - 2 * d) - 31 * s(-l + f - 2 * d) - 25 * s(-2 * l + f) - 23 * s(lp + f - 2 * d)
        + 21 * s(-l + f) + 11 * s(-lp + f - 2 * d)
    ) * _ARCSEC
    c = math.cos
    distance = (
        385000 - 20905 * c(l) - 3699 * c(2 * d - l) - 2956 * c(2 * d) - 570 * c(2 * l) + 246 * c(2 * l - 2 * d)
        - 205 * c(lp - 2 * d) - 171 * c(l + 2 * d) - 152 * c(l + lp - 2 * d)
    )
    return longitude, latitude, distance


def sun_position_km(t: float) -> np.ndarray:
    """The Sun's geocentric position, km, mean equator and equinox of date, at *t* centuries of TT since J2000."""
    return _equatorial(*sun_ecliptic(t), t)


def moon_position_km(t: float) -> np.ndarray:
    """The Moon's geocentric position, km, mean equator and equinox of date, at *t* centuries of TT since J2000."""
    return _equatorial(*moon_ecliptic(t), t)


def _density_kg_m3(h_km: np.ndarray) -> np.ndarray:
    """monte_carlo._atmo_density_kg_m3, vectorised: the band at or below each altitude, the lowest under 0 km."""
    h = np.maximum(h_km, 0.0)
    band = np.clip(np.searchsorted(_ATMOSPHERE[:, 0], h, side="right") - 1, 0, len(_ATMOSPHERE) - 1)
    base, rho0, scale = _ATMOSPHERE[band].T
    return rho0 * np.exp(-(h - base) / scale)


def _third_body(r: np.ndarray, body: np.ndarray, gm: float) -> np.ndarray:
    """A point mass's pull on each of *r* less its pull on the Earth's centre."""
    d = body - r
    return gm * (d / np.linalg.norm(d, axis=1, keepdims=True) ** 3 - body / np.linalg.norm(body) ** 3)


def zonal_j3_j4(r: np.ndarray) -> np.ndarray:
    """The J3 and J4 accelerations, km/s^2, at positions *r* (n, 3), km."""
    mu, re = monte_carlo._MU, monte_carlo._R_E
    x, y, z = r.T
    rn = np.linalg.norm(r, axis=1)
    zr = z / rn
    k3 = -2.5 * J3 * mu * re**3 / rn**5
    j3 = np.stack([
        k3 * x / rn * (3.0 * zr - 7.0 * zr**3),
        k3 * y / rn * (3.0 * zr - 7.0 * zr**3),
        k3 * (6.0 * zr**2 - 7.0 * zr**4 - 0.6),
    ], axis=1)
    k4 = 1.875 * J4 * mu * re**4 / rn**7
    j4 = np.stack([
        k4 * x * (1.0 - 14.0 * zr**2 + 21.0 * zr**4),
        k4 * y * (1.0 - 14.0 * zr**2 + 21.0 * zr**4),
        k4 * z * (5.0 - 70.0 / 3.0 * zr**2 + 21.0 * zr**4),
    ], axis=1)
    return j3 + j4


@dataclass(frozen=True)
class Objects:
    """Per object: the ballistic coefficient m / (Cd A), kg/m^2, and Cr times area-to-mass, m^2/kg."""

    ballistic_kg_m2: np.ndarray
    cr_area_to_mass_m2_kg: np.ndarray

    @classmethod
    def alike(cls, n: int, bstar: float, cr: float = SRP_CR, area_to_mass: float = SRP_AREA_TO_MASS_M2_KG) -> Objects:
        """*n* objects with the engine's ballistic coefficient for *bstar* and one radiation pressure figure."""
        return cls(np.full(n, monte_carlo._ballistic_coefficient_kg_m2(bstar)), np.full(n, cr * area_to_mass))


@dataclass(frozen=True)
class Model:
    """What a run flies: its objects, the forces on them, and the instant time zero is."""

    objects: Objects
    forces: Forces
    epoch: datetime


def acceleration(t_s: float, r: np.ndarray, v: np.ndarray, model: Model) -> np.ndarray:
    """Each object's acceleration, km/s^2, *t_s* seconds after the model's epoch: positions *r* and velocities *v*
    (n, 3)."""
    objects, forces = model.objects, model.forces
    mu, re, j2 = monte_carlo._MU, monte_carlo._R_E, monte_carlo._J2
    x, y, z = r.T
    rn = np.linalg.norm(r, axis=1)
    accel = -(mu / rn**3)[:, None] * r
    zr2 = (z / rn) ** 2
    fac = -1.5 * j2 * mu * re**2 / rn**5
    accel = accel + fac[:, None] * np.stack([x * (1.0 - 5.0 * zr2), y * (1.0 - 5.0 * zr2), z * (3.0 - 5.0 * zr2)], 1)
    h = rn - re
    speed = np.linalg.norm(v, axis=1)
    drag = (h < _DRAG_CEILING_KM) & (objects.ballistic_kg_m2 > 0.0) & (speed > _DRAG_MIN_SPEED_KM_S)
    if drag.any():
        k = -(500.0 / objects.ballistic_kg_m2[drag]) * _density_kg_m3(h[drag]) * speed[drag]
        accel[drag] += k[:, None] * v[drag]
    if forces.j3_j4:
        accel = accel + zonal_j3_j4(r)
    if not (forces.moon or forces.sun or forces.srp):
        return accel
    t = centuries_tt(model.epoch) + t_s / (_DAY_S * _JULIAN_CENTURY_DAYS)
    if forces.moon:
        accel = accel + _third_body(r, moon_position_km(t), GM_MOON)
    if forces.sun or forces.srp:
        sun = sun_position_km(t)
        if forces.sun:
            accel = accel + _third_body(r, sun, GM_SUN)
        if forces.srp:
            accel = accel + _radiation_pressure(r, sun, objects)
    return accel


def _radiation_pressure(r: np.ndarray, sun: np.ndarray, objects: Objects) -> np.ndarray:
    """Cannonball radiation pressure, km/s^2, in a cylindrical Earth shadow of the equatorial radius whose edge is
    smoothed: behind the Earth the light is a hyperbolic tangent of the distance from the shadow's axis less that
    radius, half lit on the edge and 98 per cent lit or dark SHADOW_EDGE_KM either side of it."""
    away = r - sun
    distance = np.linalg.norm(away, axis=1)
    to_sun = sun / np.linalg.norm(sun)
    along = r @ to_sun
    off_axis = np.linalg.norm(r - along[:, None] * to_sun, axis=1)
    light = np.where(along < 0.0, 0.5 * (1.0 + np.tanh(2.0 * (off_axis - monte_carlo._R_E) / SHADOW_EDGE_KM)), 1.0)
    # N/m^2 times m^2/kg is m/s^2; a thousandth of that is km/s^2.
    size = P_SUN_N_M2 * objects.cr_area_to_mass_m2_kg * (AU_KM / distance) ** 2 * 1e-3 * light
    return size[:, None] * away / distance[:, None]


def flown(
    states: np.ndarray, model: Model, times_s: Sequence[float] | np.ndarray, *, rtol: float = 1e-11,
    atol: float = 1e-11,
) -> np.ndarray:
    """*states* (n, 6) at the model's epoch flown together by DOP853 and read at *times_s*: positions and velocities
    (k, n, 6).

    DOP853 at rtol and atol 1e-11 by default: with the added forces off, tests/unit/test_force_model_error.py holds
    it within 0.002 km of the engine's own equations integrated at rtol 1e-12 over 72 h."""
    n = len(states)
    times = np.asarray(times_s, dtype=float)

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        s = y.reshape(n, 6)
        return np.hstack([s[:, 3:], acceleration(t, s[:, :3], s[:, 3:], model)]).ravel()

    sol = solve_ivp(rhs, (float(times[0]), float(times[-1])), np.asarray(states, dtype=float).ravel(),
                    method="DOP853", rtol=rtol, atol=atol, t_eval=times)
    if not sol.success:
        raise RuntimeError(sol.message)
    return np.asarray(sol.y.T.reshape(len(times), n, 6))


def flown_for(
    states: np.ndarray, spans_s: np.ndarray, objects: Objects, *, rtol: float = 1e-11, atol: float = 1e-11,
) -> np.ndarray:
    """Each of *states* (n, 6) flown by the engine's own forces for its own span, s, forward or back, together:
    the states (n, 6) at the end of each. Time is scaled to each object's span, which only a model with no clock in
    it allows, so it flies OPERATIONAL alone: a sample's burn is moved off the epoch by its timing offset this way."""
    n = len(states)
    spans = np.asarray(spans_s, dtype=float)[:, None]
    model = Model(objects, OPERATIONAL, _NO_EPOCH)

    def rhs(_s: float, y: np.ndarray) -> np.ndarray:
        x = y.reshape(n, 6)
        return (np.hstack([x[:, 3:], acceleration(0.0, x[:, :3], x[:, 3:], model)])
                * spans).ravel()

    sol = solve_ivp(rhs, (0.0, 1.0), np.asarray(states, dtype=float).ravel(), method="DOP853", rtol=rtol, atol=atol)
    if not sol.success:
        raise RuntimeError(sol.message)
    return np.asarray(sol.y[:, -1].reshape(n, 6))
