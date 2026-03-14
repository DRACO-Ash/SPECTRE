"""Orbit representation and SGP4 propagation.

Wraps the sgp4 library to propagate TLE-defined satellites and compute
position/velocity state vectors at arbitrary epochs.  Also supports
creating simple circular/elliptical orbits from Keplerian elements for
use in transfer calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from sgp4.api import Satrec, jday

from sipc.astro.constants import MU_EARTH, R_EARTH


@dataclass
class StateVector:
    """Cartesian state vector at a specific epoch."""

    epoch: datetime
    r: np.ndarray  # km   — position (3,) in TEME
    v: np.ndarray  # km/s — velocity (3,) in TEME

    @property
    def r_mag(self) -> float:
        return float(np.linalg.norm(self.r))

    @property
    def v_mag(self) -> float:
        return float(np.linalg.norm(self.v))

    @property
    def altitude_km(self) -> float:
        """Altitude above Earth's equatorial surface."""
        return self.r_mag - R_EARTH


@dataclass
class KeplerianElements:
    """Classical orbital elements."""

    a: float          # km — semi-major axis
    ecc: float        # eccentricity
    inc: float        # degrees — inclination
    raan: float       # degrees — right ascension of ascending node
    argp: float       # degrees — argument of periapsis
    ta: float         # degrees — true anomaly
    epoch: datetime | None = None

    @property
    def period_s(self) -> float:
        """Orbital period in seconds."""
        return 2.0 * math.pi * math.sqrt(self.a ** 3 / MU_EARTH)

    @property
    def apoapsis(self) -> float:
        """Apoapsis radius in km."""
        return self.a * (1.0 + self.ecc)

    @property
    def periapsis(self) -> float:
        """Periapsis radius in km."""
        return self.a * (1.0 - self.ecc)


class TLEOrbit:
    """Satellite orbit defined by a TLE, propagated with SGP4."""

    def __init__(self, tle: str) -> None:
        lines = [ln.strip() for ln in tle.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            raise ValueError("TLE must have at least 2 lines")
        self.line1 = lines[-2]
        self.line2 = lines[-1]
        self._sat = Satrec.twoline2rv(self.line1, self.line2)

    def propagate(self, epoch: datetime) -> StateVector:
        """Propagate to *epoch* and return the TEME state vector."""
        jd, fr = _datetime_to_jd(epoch)
        e, r, v = self._sat.sgp4(jd, fr)
        if e != 0:
            raise RuntimeError(f"SGP4 error code {e} at {epoch}")
        return StateVector(
            epoch=epoch,
            r=np.array(r, dtype=float),
            v=np.array(v, dtype=float),
        )

    def propagate_range(
        self,
        start: datetime,
        stop: datetime,
        step_s: float = 60.0,
    ) -> list[StateVector]:
        """Propagate over a time window, returning a state vector per step."""
        states: list[StateVector] = []
        window = (stop - start).total_seconds()
        n = max(1, int(window / step_s))
        for i in range(n + 1):
            t = start + timedelta(seconds=i * step_s)
            try:
                states.append(self.propagate(t))
            except RuntimeError:
                continue
        return states

    def keplerian_at(self, epoch: datetime) -> KeplerianElements:
        """Compute classical Keplerian elements at *epoch*."""
        sv = self.propagate(epoch)
        return state_to_keplerian(sv)


def state_to_keplerian(sv: StateVector) -> KeplerianElements:
    """Convert a Cartesian state vector to classical orbital elements."""
    r = sv.r
    v = sv.v
    r_mag = sv.r_mag
    v_mag = sv.v_mag

    # Specific angular momentum.
    h = np.cross(r, v)
    h_mag = float(np.linalg.norm(h))

    # Node vector.
    k_hat = np.array([0.0, 0.0, 1.0])
    n = np.cross(k_hat, h)
    n_mag = float(np.linalg.norm(n))

    # Eccentricity vector.
    e_vec = ((v_mag ** 2 - MU_EARTH / r_mag) * r - np.dot(r, v) * v) / MU_EARTH
    ecc = float(np.linalg.norm(e_vec))

    # Semi-major axis.
    energy = v_mag ** 2 / 2.0 - MU_EARTH / r_mag
    if abs(energy) < 1e-14:
        a = float("inf")  # parabolic
    else:
        a = -MU_EARTH / (2.0 * energy)

    # Inclination.
    inc = math.degrees(math.acos(np.clip(h[2] / h_mag, -1.0, 1.0)))

    # RAAN.
    if n_mag > 1e-10:
        raan = math.degrees(math.acos(np.clip(n[0] / n_mag, -1.0, 1.0)))
        if n[1] < 0:
            raan = 360.0 - raan
    else:
        raan = 0.0

    # Argument of periapsis.
    if n_mag > 1e-10 and ecc > 1e-10:
        argp = math.degrees(
            math.acos(np.clip(np.dot(n, e_vec) / (n_mag * ecc), -1.0, 1.0))
        )
        if e_vec[2] < 0:
            argp = 360.0 - argp
    else:
        argp = 0.0

    # True anomaly.
    if ecc > 1e-10:
        cos_ta = np.clip(np.dot(e_vec, r) / (ecc * r_mag), -1.0, 1.0)
        ta = math.degrees(math.acos(cos_ta))
        if np.dot(r, v) < 0:
            ta = 360.0 - ta
    else:
        ta = 0.0

    return KeplerianElements(
        a=a, ecc=ecc, inc=inc, raan=raan, argp=argp, ta=ta, epoch=sv.epoch,
    )


def keplerian_to_state(
    elem: KeplerianElements,
    mu: float = MU_EARTH,
) -> StateVector:
    """Convert Keplerian elements to a Cartesian state vector.

    Useful for setting up Lambert problem inputs from known orbits.
    """
    a, ecc = elem.a, elem.ecc
    inc_r = math.radians(elem.inc)
    raan_r = math.radians(elem.raan)
    argp_r = math.radians(elem.argp)
    ta_r = math.radians(elem.ta)

    # Perifocal frame.
    p = a * (1.0 - ecc ** 2)
    r_pf = p / (1.0 + ecc * math.cos(ta_r))
    r_perifocal = np.array([r_pf * math.cos(ta_r), r_pf * math.sin(ta_r), 0.0])
    v_perifocal = math.sqrt(mu / p) * np.array([
        -math.sin(ta_r),
        ecc + math.cos(ta_r),
        0.0,
    ])

    # Rotation matrix: perifocal → ECI.
    cos_O, sin_O = math.cos(raan_r), math.sin(raan_r)
    cos_w, sin_w = math.cos(argp_r), math.sin(argp_r)
    cos_i, sin_i = math.cos(inc_r), math.sin(inc_r)

    R = np.array([
        [cos_O * cos_w - sin_O * sin_w * cos_i,
         -cos_O * sin_w - sin_O * cos_w * cos_i,
         sin_O * sin_i],
        [sin_O * cos_w + cos_O * sin_w * cos_i,
         -sin_O * sin_w + cos_O * cos_w * cos_i,
         -cos_O * sin_i],
        [sin_w * sin_i,
         cos_w * sin_i,
         cos_i],
    ])

    r_eci = R @ r_perifocal
    v_eci = R @ v_perifocal

    return StateVector(
        epoch=elem.epoch or datetime.now(tz=UTC),
        r=r_eci,
        v=v_eci,
    )


def _datetime_to_jd(dt: datetime) -> tuple[float, float]:
    """Convert a datetime to Julian date (jd, fraction) for sgp4."""
    sec = dt.second + dt.microsecond / 1e6
    return jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, sec)
