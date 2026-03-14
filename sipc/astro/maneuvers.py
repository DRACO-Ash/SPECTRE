"""Intercept maneuver calculations for the SIPC intercept engine.

Wraps the Lambert solver, Hohmann, and bi-elliptic transfer primitives
to produce multi-burn intercept solutions from TLE-propagated satellite
state vectors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from sipc.astro.constants import MU_EARTH, R_EARTH
from sipc.astro.lambert import LambertSolution, solve_lambert
from sipc.astro.propagator import TLEOrbit, StateVector, state_to_keplerian
from sipc.astro.transfers import TransferResult, hohmann, bielliptic


@dataclass
class Burn:
    """A single impulsive burn in an intercept plan."""

    burn_number: int
    epoch: datetime
    delta_v: np.ndarray       # km/s — VNB or ECI delta-V vector (3,)
    delta_v_mag: float        # km/s — magnitude
    dv_prograde: float = 0.0  # km/s — along-track component
    dv_normal: float = 0.0    # km/s — cross-track component
    dv_radial: float = 0.0    # km/s — radial component


@dataclass
class InterceptSolution:
    """Complete intercept solution with per-burn breakdown.

    This is the astro-layer result; the web layer maps it to
    ``domain.models.InterceptResult`` for display.
    """

    method: str
    burns: list[Burn] = field(default_factory=list)
    total_delta_v: float = 0.0        # km/s
    departure_epoch: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    arrival_epoch: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    miss_distance_km: float = 0.0     # km — actual miss at arrival
    lambert_solution: LambertSolution | None = None
    transfer_result: TransferResult | None = None


def lambert_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    tof_s: float,
    coast_s: float = 0.0,
    target_distance_km: float = 0.0,
    prograde: bool = True,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a Lambert-based intercept from red to blue.

    1. Propagate red to manoeuvre_start + coast → departure position.
    2. Propagate blue to departure + tof → arrival position.
    3. Solve Lambert's problem for the transfer arc.
    4. Compute impulse burns at departure and (optionally) arrival.

    Args:
        red_tle: TLE of the interceptor (red) satellite.
        blue_tle: TLE of the target (blue) satellite.
        manoeuvre_start: UTC time when the manoeuvre sequence begins.
        tof_s: Time of flight for the transfer arc (seconds).
        coast_s: Coast time before the first burn (seconds).
        target_distance_km: Desired miss distance at arrival (km).
        prograde: Use prograde (short-way) transfer arc.
        mu: Gravitational parameter (km³/s²).

    Returns:
        :class:`InterceptSolution` with two burns (departure + arrival).
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    t_arrival = t_departure + timedelta(seconds=tof_s)

    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_arrival)

    # If a standoff distance is requested, adjust the target position
    # along the line from Earth centre to the blue satellite.
    r_target = sv_blue.r.copy()
    if target_distance_km > 0:
        r_hat = sv_blue.r / np.linalg.norm(sv_blue.r)
        r_target = sv_blue.r - r_hat * target_distance_km

    sol = solve_lambert(
        r1=sv_red.r,
        r2=r_target,
        tof=tof_s,
        mu=mu,
        prograde=prograde,
        v1_initial=sv_red.v,
        v2_target=sv_blue.v,
    )

    # Decompose delta-V into VNB (prograde/normal/radial) frame.
    burn1 = _make_burn(1, t_departure, sol.delta_v1, sv_red)
    burn2 = _make_burn(2, t_arrival, sol.delta_v2, sv_blue)

    # Actual miss distance at arrival.
    miss = float(np.linalg.norm(r_target - sv_blue.r)) if target_distance_km > 0 else 0.0

    return InterceptSolution(
        method="lambert",
        burns=[burn1, burn2],
        total_delta_v=sol.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=target_distance_km,
        lambert_solution=sol,
    )


def hohmann_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a Hohmann transfer intercept.

    Approximates both orbits as circular at their current radii.
    Best for coplanar near-circular orbits at different altitudes.

    Args:
        red_tle: TLE of the interceptor.
        blue_tle: TLE of the target.
        manoeuvre_start: When the manoeuvre sequence begins.
        coast_s: Coast before first burn (seconds).
        mu: Gravitational parameter.

    Returns:
        :class:`InterceptSolution` with two burns.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r1 = sv_red.r_mag
    r2 = sv_blue.r_mag

    result = hohmann(r1, r2, mu)
    t_arrival = t_departure + timedelta(seconds=result.transfer_time_s)

    # Departure burn is along velocity direction (prograde).
    v_hat = sv_red.v / sv_red.v_mag
    dv1_vec = v_hat * result.delta_v_1
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

    # Arrival burn — propagate blue to arrival time for frame reference.
    sv_blue_arr = blue_orbit.propagate(t_arrival)
    v_hat_arr = sv_blue_arr.v / sv_blue_arr.v_mag
    dv2_vec = v_hat_arr * result.delta_v_2
    burn2 = _make_burn(2, t_arrival, dv2_vec, sv_blue_arr)

    return InterceptSolution(
        method="hohmann",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=0.0,
        transfer_result=result,
    )


def bielliptic_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    rb_km: float | None = None,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a bi-elliptic transfer intercept.

    Args:
        red_tle: TLE of the interceptor.
        blue_tle: TLE of the target.
        manoeuvre_start: When the manoeuvre sequence begins.
        rb_km: Intermediate apoapsis radius (km). If None, defaults to
               1.5× max(r1, r2).
        coast_s: Coast before first burn (seconds).
        mu: Gravitational parameter.

    Returns:
        :class:`InterceptSolution` with three burns.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r1 = sv_red.r_mag
    r2 = sv_blue.r_mag
    if rb_km is None:
        rb_km = 1.5 * max(r1, r2)

    result = bielliptic(r1, r2, rb_km, mu)
    t_arrival = t_departure + timedelta(seconds=result.transfer_time_s)

    # Burns: departure, intermediate apoapsis, circularise at target.
    v_hat = sv_red.v / sv_red.v_mag
    burn1 = _make_burn(1, t_departure, v_hat * result.delta_v_1, sv_red)

    # Intermediate burn at apoapsis of first transfer ellipse.
    t_mid = t_departure + timedelta(
        seconds=math.pi * math.sqrt(((r1 + rb_km) / 2.0) ** 3 / mu)
    )
    sv_red_mid = red_orbit.propagate(t_mid)
    burn2 = _make_burn(2, t_mid, v_hat * result.delta_v_2, sv_red_mid)

    sv_blue_arr = blue_orbit.propagate(t_arrival)
    v_hat_arr = sv_blue_arr.v / sv_blue_arr.v_mag
    burn3 = _make_burn(3, t_arrival, v_hat_arr * result.delta_v_3, sv_blue_arr)

    return InterceptSolution(
        method="bielliptic",
        burns=[burn1, burn2, burn3],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=0.0,
        transfer_result=result,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_burn(
    number: int,
    epoch: datetime,
    dv_eci: np.ndarray,
    sv: StateVector,
) -> Burn:
    """Create a Burn with VNB decomposition from an ECI delta-V vector."""
    mag = float(np.linalg.norm(dv_eci))
    if mag < 1e-14:
        return Burn(burn_number=number, epoch=epoch, delta_v=dv_eci, delta_v_mag=0.0)

    # VNB frame: V = along-track, N = orbit-normal, B = radial
    v_hat = sv.v / sv.v_mag if sv.v_mag > 1e-10 else np.array([1, 0, 0], dtype=float)
    h = np.cross(sv.r, sv.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    prograde = float(np.dot(dv_eci, v_hat))
    normal = float(np.dot(dv_eci, n_hat))
    radial = float(np.dot(dv_eci, b_hat))

    return Burn(
        burn_number=number,
        epoch=epoch,
        delta_v=dv_eci,
        delta_v_mag=mag,
        dv_prograde=prograde,
        dv_normal=normal,
        dv_radial=radial,
    )
