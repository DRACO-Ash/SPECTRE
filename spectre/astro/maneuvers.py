"""Intercept maneuver calculations for the SPECTRE intercept engine.

Wraps the Lambert solver, Hohmann, and bi-elliptic transfer primitives
to produce multi-burn intercept solutions from TLE-propagated satellite
state vectors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from spectre.astro.constants import MU_EARTH, R_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate, _eci_to_hill_matrix, _initial_hill_state
from spectre.astro.kepler import propagate_two_body
from spectre.astro.lambert import LambertSolution, cheapest_lambert, solve_lambert
from spectre.astro.propagator import StateVector, TLEOrbit, state_to_keplerian
from spectre.astro.tactical import (
    EvasionResult,
    assess_intercept_intent,
    classify_manoeuvre,
    collision_avoidance,
    combined_altitude_plane_change,
    cw_along_track_drift,
    cw_radial_separation,
    detectability_metric,
    fingerprint_manoeuvre,
    formation_defence_burn,
    geo_drift,
    hbar_hop_sequence,
    j2_drift_plan,
    optimal_evasion,
    orbital_terrain,
    phasing_orbit,
    relative_motion_stability,
    vbar_hop_sequence,
)
from spectre.astro.transfers import TransferResult, bielliptic, hohmann

# NMC insertion: the ellipse through red's position may differ from the one
# requested by this fraction, and the closest approach is sampled this often.
_NMC_SIZE_TOLERANCE = 0.10
_NMC_SAMPLES = 2000


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
    miss_distance_km: float = 0.0     # km — actual miss at arrival, and nothing else
    lambert_solution: LambertSolution | None = None
    transfer_result: TransferResult | None = None
    # Assessment methods report a score, not a distance. They used to write it
    # into miss_distance_km, so seven scores travelled to the web layer typed
    # and named as kilometres (audit F-072).
    score: float | None = None        # 0-100, or a count for the envelope
    score_kind: str = ""              # what the score measures
    provenance: str = "physics"       # "physics": solved; "heuristic": uncalibrated weights


def lambert_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    tof_s: float,
    coast_s: float = 0.0,
    target_distance_km: float = 0.0,
    prograde: bool | None = None,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a Lambert-based intercept from red to blue.

    1. Propagate red to manoeuvre_start + coast → departure position.
    2. Propagate blue to departure + tof → arrival position.
    3. Solve Lambert's problem for the transfer arc, taking the cheapest of
       the zero-revolution and every multi-revolution solution. A flight
       longer than about one orbit otherwise priced the zero-revolution arc,
       several km/s where going round once costs m/s (audit F-010).
    4. Compute impulse burns at departure and (optionally) arrival.

    Args:
        red_tle: TLE of the interceptor (red) satellite.
        blue_tle: TLE of the target (blue) satellite.
        manoeuvre_start: UTC time when the manoeuvre sequence begins.
        tof_s: Time of flight for the transfer arc (seconds).
        coast_s: Coast time before the first burn (seconds).
        target_distance_km: Desired miss distance at arrival (km).
        prograde: Transfer sense passed to :func:`solve_lambert`; ``None``
            (default) follows red's own direction of motion.
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

    sol = cheapest_lambert(
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
    _miss = float(np.linalg.norm(r_target - sv_blue.r)) if target_distance_km > 0 else 0.0

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

    # transfers.hohmann returns magnitudes. Raising burns are prograde and
    # lowering burns retrograde, along the interceptor's own velocity at each
    # burn; the arrival state comes from propagating the transfer arc.
    sense = 1.0 if r2 >= r1 else -1.0
    dv1_vec = sense * result.delta_v_1 * sv_red.v / sv_red.v_mag
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

    sv_arr = _coast(sv_red, dv1_vec, t_arrival, mu)
    dv2_vec = sense * result.delta_v_2 * sv_arr.v / sv_arr.v_mag
    burn2 = _make_burn(2, t_arrival, dv2_vec, sv_arr)

    return InterceptSolution(
        method="hohmann",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=_separation(sv_arr, blue_orbit),
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

    # Burn 1 raises apoapsis to rb. Burn 2, at rb, moves perigee to r2:
    # prograde when that raises it, retrograde when it lowers it. Burn 3
    # circularises at the perigee of the second ellipse, which is always a
    # retrograde burn. Each is pointed along the interceptor's velocity on the
    # transfer arc at that instant, from propagating the arc.
    dv1_vec = result.delta_v_1 * sv_red.v / sv_red.v_mag
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

    t_mid = t_departure + timedelta(
        seconds=math.pi * math.sqrt(((r1 + rb_km) / 2.0) ** 3 / mu)
    )
    sv_mid = _coast(sv_red, dv1_vec, t_mid, mu)
    sense = 1.0 if r2 >= r1 else -1.0
    dv2_vec = sense * result.delta_v_2 * sv_mid.v / sv_mid.v_mag
    burn2 = _make_burn(2, t_mid, dv2_vec, sv_mid)

    sv_arr = _coast(sv_mid, dv2_vec, t_arrival, mu)
    dv3_vec = -result.delta_v_3 * sv_arr.v / sv_arr.v_mag
    burn3 = _make_burn(3, t_arrival, dv3_vec, sv_arr)

    return InterceptSolution(
        method="bielliptic",
        burns=[burn1, burn2, burn3],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=_separation(sv_arr, blue_orbit),
        transfer_result=result,
    )


def phasing_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    n_revolutions: int = 1,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a phasing orbit manoeuvre to close angular separation.

    The red satellite adjusts its period to arrive at the blue satellite's
    angular position after *n_revolutions* of the phasing orbit.

    Args:
        red_tle: TLE of the interceptor.
        blue_tle: TLE of the target.
        manoeuvre_start: When the sequence begins.
        n_revolutions: Phasing orbit revolutions (1–10).
        coast_s: Coast before first burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_red = sv_red.r_mag
    r_blue = sv_blue.r_mag

    # Phase angle from position vectors
    cos_angle = float(np.dot(sv_red.r, sv_blue.r) / (r_red * r_blue))
    cos_angle = max(-1.0, min(1.0, cos_angle))
    phase_deg = math.degrees(math.acos(cos_angle))

    # Determine sign: is blue ahead or behind?
    cross = np.cross(sv_red.r, sv_blue.r)
    h_red = np.cross(sv_red.r, sv_red.v)
    if float(np.dot(cross, h_red)) < 0:
        phase_deg = 360.0 - phase_deg

    result = phasing_orbit(r_red, r_blue, phase_deg, n_revolutions, mu)
    t_arrival = t_departure + timedelta(seconds=result.time_to_intercept_s)

    # Burn 1: enter phasing orbit (prograde adjustment)
    v_hat = sv_red.v / sv_red.v_mag
    dv1_vec = v_hat * (-result.delta_v_1 if result.phasing_sma_km < r_red else result.delta_v_1)
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

    # Burn 2: return to original orbit at arrival
    sv_red_arr = red_orbit.propagate(t_arrival)
    v_hat_arr = sv_red_arr.v / sv_red_arr.v_mag
    dv2_vec = v_hat_arr * (result.delta_v_2 if result.phasing_sma_km < r_red else -result.delta_v_2)
    burn2 = _make_burn(2, t_arrival, dv2_vec, sv_red_arr)

    return InterceptSolution(
        method="phasing",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=0.0,
    )


def cw_radial_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    desired_separation_km: float = 5.0,
    time_s: float = 1800.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """CW radial separation manoeuvre.

    Computes a single radial impulse to produce desired radial separation
    at the specified time using Hill/Clohessy-Wiltshire equations.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the reference satellite.
        manoeuvre_start: When the sequence begins.
        desired_separation_km: Target radial separation (km).
        time_s: Evaluation time after impulse (seconds).
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0
    cw = cw_radial_separation(r_ref, desired_separation_km, time_s, mu)

    t_arrival = t_departure + timedelta(seconds=time_s)

    # Radial impulse in the radial direction (binormal in VNB)
    v_hat = sv_red.v / sv_red.v_mag
    h = np.cross(sv_red.r, sv_red.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)  # radial direction

    dv_vec = b_hat * cw.delta_v_radial
    burn1 = _make_burn(1, t_departure, dv_vec, sv_red)

    _notes = (
        f"CW radial: {desired_separation_km:.1f} km separation in "
        f"{time_s / 60:.0f} min, along-track drift {cw.along_track_sep_km:.1f} km"
    )

    return InterceptSolution(
        method="rbar_hop",
        burns=[burn1],
        total_delta_v=cw.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=desired_separation_km,
    )


def cw_drift_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    desired_drift_km: float = 10.0,
    time_s: float = 3600.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """CW along-track drift manoeuvre.

    Computes a single along-track impulse to produce desired along-track
    displacement at the specified time.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the reference satellite.
        manoeuvre_start: When the sequence begins.
        desired_drift_km: Target along-track displacement (km).
        time_s: Evaluation time after impulse (seconds).
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0
    cw = cw_along_track_drift(r_ref, desired_drift_km, time_s, mu)

    t_arrival = t_departure + timedelta(seconds=time_s)

    # Along-track impulse in velocity direction
    v_hat = sv_red.v / sv_red.v_mag
    dv_vec = v_hat * cw.delta_v_along_track
    burn1 = _make_burn(1, t_departure, dv_vec, sv_red)

    return InterceptSolution(
        method="cw_drift",
        burns=[burn1],
        total_delta_v=cw.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=desired_drift_km,
    )


def vbar_hop_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    n_hops: int = 3,
    hop_distance_km: float | None = None,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """V-bar hop approach sequence along the velocity vector.

    Executes a multi-hop V-bar approach using two radial burns per hop.
    If *hop_distance_km* is ``None``, derives it from the current
    along-track separation divided by *n_hops*.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the target satellite.
        manoeuvre_start: When the sequence begins.
        n_hops: Number of discrete hops.
        hop_distance_km: Along-track advance per hop (km); auto-derived if None.
        coast_s: Coast before the first hop (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0

    if hop_distance_km is None:
        dr = np.array(sv_blue.r) - np.array(sv_red.r)
        v_hat_d = sv_red.v / sv_red.v_mag
        along_track_sep = abs(float(np.dot(dr, v_hat_d)))
        hop_distance_km = max(along_track_sep / n_hops, 1.0)

    result = vbar_hop_sequence(r_ref, hop_distance_km, n_hops, mu=mu)
    t_arrival = t_departure + timedelta(seconds=result.total_time_s)

    # First radial burn (entry): magnitude = dv_per_hop / 2
    v_hat = sv_red.v / sv_red.v_mag
    h_vec = np.cross(sv_red.r, sv_red.v)
    h_mag = float(np.linalg.norm(h_vec))
    n_hat = h_vec / h_mag if h_mag > 1e-10 else np.array([0.0, 0.0, 1.0])
    b_hat = np.cross(v_hat, n_hat)  # radial direction
    dv_mag = result.delta_v_per_hop / 2.0
    burn1 = _make_burn(1, t_departure, b_hat * dv_mag, sv_red)

    # Final corrective burn (anti-radial, closing the last hop)
    sv_red_arr = red_orbit.propagate(t_arrival)
    v_hat_a = sv_red_arr.v / sv_red_arr.v_mag
    h_a = np.cross(sv_red_arr.r, sv_red_arr.v)
    h_a_mag = float(np.linalg.norm(h_a))
    n_hat_a = h_a / h_a_mag if h_a_mag > 1e-10 else np.array([0.0, 0.0, 1.0])
    b_hat_a = np.cross(v_hat_a, n_hat_a)
    burn2 = _make_burn(2, t_arrival, -b_hat_a * dv_mag, sv_red_arr)

    return InterceptSolution(
        method="vbar_hop",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=result.total_advance_km,
    )


def hbar_hop_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    n_hops: int = 3,
    hop_distance_km: float | None = None,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """H-bar hop approach sequence in the orbit-normal direction.

    Executes a multi-hop H-bar approach using normal burns at node
    crossings.  If *hop_distance_km* is ``None``, derives it from the
    current cross-track separation divided by *n_hops*.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the target satellite.
        manoeuvre_start: When the sequence begins.
        n_hops: Number of discrete hops.
        hop_distance_km: Orbit-normal advance per hop (km); auto-derived if None.
        coast_s: Coast before the first hop (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0

    if hop_distance_km is None:
        dr = np.array(sv_blue.r) - np.array(sv_red.r)
        h_vec0 = np.cross(sv_red.r, sv_red.v)
        h_mag0 = float(np.linalg.norm(h_vec0))
        n_hat0 = h_vec0 / h_mag0 if h_mag0 > 1e-10 else np.array([0.0, 0.0, 1.0])
        cross_track_sep = abs(float(np.dot(dr, n_hat0)))
        hop_distance_km = max(cross_track_sep / n_hops, 1.0)

    result = hbar_hop_sequence(r_ref, hop_distance_km, n_hops, mu=mu)
    t_arrival = t_departure + timedelta(seconds=result.total_time_s)

    # First normal burn in the orbit-normal (H-bar) direction
    h_vec = np.cross(sv_red.r, sv_red.v)
    h_mag = float(np.linalg.norm(h_vec))
    n_hat = h_vec / h_mag if h_mag > 1e-10 else np.array([0.0, 0.0, 1.0])
    burn1 = _make_burn(1, t_departure, n_hat * result.delta_v_per_hop, sv_red)

    # Final corrective burn (anti-normal)
    sv_red_arr = red_orbit.propagate(t_arrival)
    h_arr = np.cross(sv_red_arr.r, sv_red_arr.v)
    h_arr_mag = float(np.linalg.norm(h_arr))
    n_hat_arr = h_arr / h_arr_mag if h_arr_mag > 1e-10 else np.array([0.0, 0.0, 1.0])
    burn2 = _make_burn(2, t_arrival, n_hat_arr * result.delta_v_per_hop, sv_red_arr)

    return InterceptSolution(
        method="hbar_hop",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=result.total_advance_km,
    )


# Below this |h| (km^2/s) the state is rectilinear and has no orbit plane.
_DEGENERATE_ANGULAR_MOMENTUM: float = 1e-10
# A position this close to the plane (km) is on it.
_ON_PLANE_KM: float = 1e-6
# Plane-crossing time refined to this resolution (seconds).
_CROSSING_RESOLUTION_S: float = 0.1


def _unit_normal(sv: StateVector) -> np.ndarray:
    """Return the unit orbit normal h / |h| for *sv*."""
    h = np.cross(sv.r, sv.v)
    h_mag = float(np.linalg.norm(h))
    return h / h_mag if h_mag > _DEGENERATE_ANGULAR_MOMENTUM else np.array([0.0, 0.0, 1.0])


def _next_plane_crossing(
    orbit: TLEOrbit, plane_normal: np.ndarray, start: datetime, period_s: float,
) -> datetime:
    """Return the first time at or after *start* that *orbit* crosses a plane.

    The plane passes through the Earth's centre with unit normal
    *plane_normal*. Sampled at one-minute steps over one period, then refined
    by bisection to a tenth of a second. Coplanar orbits return *start*.
    """
    def height(t: datetime) -> float:
        return float(np.dot(orbit.propagate(t).r, plane_normal))

    step = timedelta(seconds=60.0)
    t0, f0 = start, height(start)
    if abs(f0) < _ON_PLANE_KM:
        return start
    end = start + timedelta(seconds=period_s)
    while t0 < end:
        t1 = t0 + step
        f1 = height(t1)
        if f0 * f1 <= 0.0:
            while (t1 - t0).total_seconds() > _CROSSING_RESOLUTION_S:
                tm = t0 + (t1 - t0) / 2
                fm = height(tm)
                if f0 * fm <= 0.0:
                    t1 = tm
                else:
                    t0, f0 = tm, fm
            return t1
        t0, f0 = t1, f1
    return start


def plane_change_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute plane change to align red satellite with blue orbital plane.

    If both satellites are at similar altitudes, performs a pure inclination
    change. If altitudes differ, performs a combined altitude + plane change.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the target satellite.
        manoeuvre_start: When the sequence begins.
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    kep_red = state_to_keplerian(sv_red)

    h_red_hat = _unit_normal(sv_red)
    h_blue_hat = _unit_normal(sv_blue)
    r_red = sv_red.r_mag
    r_blue = sv_blue.r_mag
    alt_diff = abs(r_blue - r_red)

    if alt_diff < 50.0:
        # Similar altitude: a pure plane change, which only aligns the planes
        # if it is flown where the red orbit crosses the blue plane.
        period_s = 2.0 * math.pi * math.sqrt(kep_red.a**3 / mu)
        t_burn = _next_plane_crossing(red_orbit, h_blue_hat, t_departure, period_s)
        sv_burn = red_orbit.propagate(t_burn)

        # Rotate the velocity into the blue plane about the radius vector,
        # keeping the radial and transverse speeds. The burn is the difference.
        r_hat = sv_burn.r / sv_burn.r_mag
        v_radial = float(np.dot(sv_burn.v, r_hat))
        h_mag = float(np.linalg.norm(np.cross(sv_burn.r, sv_burn.v)))
        v_after = v_radial * r_hat + (h_mag / sv_burn.r_mag) * np.cross(h_blue_hat, r_hat)
        dv_vec = v_after - sv_burn.v
        burn1 = _make_burn(1, t_burn, dv_vec, sv_burn)
        dv_mag = float(np.linalg.norm(dv_vec))

        return InterceptSolution(
            method="plane_change",
            burns=[burn1],
            total_delta_v=dv_mag,
            departure_epoch=t_burn,
            arrival_epoch=t_burn,
            miss_distance_km=0.0,
        )
    # Different altitudes: a Hohmann-like transfer with the plane change on
    # the slower burn, as combined_altitude_plane_change prices it.
    period_s = 2.0 * math.pi * math.sqrt(kep_red.a**3 / mu)
    return _combined_plane_transfer(
        red_orbit, blue_orbit, (h_red_hat, h_blue_hat),
        _next_plane_crossing(red_orbit, h_blue_hat, t_departure, period_s),
        mu=mu,
    )


def _combined_plane_transfer(
    red_orbit: TLEOrbit,
    blue_orbit: TLEOrbit,
    normals: tuple[np.ndarray, np.ndarray],
    t_departure: datetime,
    *,
    mu: float,
) -> InterceptSolution:
    """Fly the combined altitude and plane change from a crossing of the blue plane.

    Departing on the line of nodes puts the arrival, half a transfer ellipse
    later, on it too, so either burn can rotate into the blue plane. Raising,
    burn 1 stays in the red plane and burn 2 turns into the blue one;
    lowering, burn 1 turns and burn 2 only circularises. Each burn is the
    difference between the velocity the geometry calls for and the velocity
    the interceptor has, so the vectors are the ones that were priced.
    """
    h_red_hat, h_blue_hat = normals
    # The angle between the two orbit PLANES, not the inclination difference.
    # Two 53 deg planes 10 deg apart in RAAN are 8 deg apart, and using
    # inclination alone priced aligning them at zero (audit F-002).
    plane_angle_deg = math.degrees(math.acos(float(np.clip(np.dot(h_red_hat, h_blue_hat), -1.0, 1.0))))
    sv_dep = red_orbit.propagate(t_departure)
    r1 = sv_dep.r_mag
    r2 = blue_orbit.propagate(t_departure).r_mag
    cpc = combined_altitude_plane_change(r1, r2, plane_angle_deg, mu)
    a_t = (r1 + r2) / 2.0

    r_hat = sv_dep.r / r1
    first_plane = h_red_hat if r2 > r1 else h_blue_hat
    v_transfer = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t)) * np.cross(first_plane, r_hat)
    dv1_vec = v_transfer - sv_dep.v
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_dep)

    t_arrival = t_departure + timedelta(seconds=cpc.transfer_time_s)
    sv_arr = _coast(sv_dep, dv1_vec, t_arrival, mu)
    r_hat_arr = sv_arr.r / sv_arr.r_mag
    dv2_vec = math.sqrt(mu / r2) * np.cross(h_blue_hat, r_hat_arr) - sv_arr.v
    burn2 = _make_burn(2, t_arrival, dv2_vec, sv_arr)

    return InterceptSolution(
        method="plane_change",
        burns=[burn1, burn2],
        total_delta_v=burn1.delta_v_mag + burn2.delta_v_mag,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=_separation(sv_arr, blue_orbit),
    )


def j2_drift_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Analyse J2 RAAN drift for orbital plane alignment.

    Returns an InterceptSolution whose two burns are the Hohmann altitude
    change that halves the natural convergence time. When no altitude in
    range achieves that, there are no burns and the arrival is the natural
    convergence.

    Raises:
        ValueError: when the planes never converge and no altitude helps.

    Args:
        red_tle: TLE of the chaser.
        blue_tle: TLE of the target.
        manoeuvre_start: Analysis epoch.
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    sv_blue = blue_orbit.propagate(t_epoch)

    kep_red = state_to_keplerian(sv_red)
    kep_blue = state_to_keplerian(sv_blue)

    # RAAN difference
    delta_raan = kep_red.raan - kep_blue.raan
    if delta_raan > 180.0:
        delta_raan -= 360.0
    elif delta_raan < -180.0:
        delta_raan += 360.0

    result = j2_drift_plan(
        kep_red.a, kep_red.ecc, kep_red.inc,
        kep_blue.a, kep_blue.ecc, kep_blue.inc,
        delta_raan, mu,
    )

    if not math.isfinite(result.accel_convergence_days):
        raise ValueError(
            "the two planes precess at the same rate, so J2 drift never closes the "
            f"{delta_raan:.2f} deg RAAN gap, and no altitude change in range speeds it"
        )

    # The altitude change is a Hohmann transfer: two burns, prograde to raise
    # and retrograde to lower, along the transfer arc's velocity.
    burns = []
    if result.accel_altitude_change_km:
        r_new = sv_red.r_mag + result.accel_altitude_change_km
        hop = hohmann(sv_red.r_mag, r_new, mu)
        sense = 1.0 if result.accel_altitude_change_km > 0 else -1.0
        dv1_vec = sense * hop.delta_v_1 * sv_red.v / sv_red.v_mag
        sv_top = _coast(sv_red, dv1_vec, t_epoch + timedelta(seconds=hop.transfer_time_s), mu)
        dv2_vec = sense * hop.delta_v_2 * sv_top.v / sv_top.v_mag
        burns = [_make_burn(1, t_epoch, dv1_vec, sv_red), _make_burn(2, sv_top.epoch, dv2_vec, sv_top)]

    t_arrival = t_epoch + timedelta(days=result.accel_convergence_days)

    _notes = (
        f"J2 drift: ΔRAAN={delta_raan:.2f}°, "
        f"natural convergence {result.convergence_time_days:.1f} days "
        f"({result.differential_rate_deg_day:.4f}°/day), "
        f"with Δalt={result.accel_altitude_change_km:.0f} km → "
        f"{result.accel_convergence_days:.1f} days"
    )

    return InterceptSolution(
        method="j2_drift",
        burns=burns,
        total_delta_v=sum(b.delta_v_mag for b in burns),
        departure_epoch=t_epoch,
        arrival_epoch=t_arrival,
        score=abs(delta_raan),
        score_kind="RAAN gap (deg)",
    )


def cola_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    desired_miss_km: float = 1.0,
    time_before_tca_s: float = 3600.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Minimum-ΔV collision avoidance manoeuvre.

    Computes the cheapest single-impulse burn (radial, along-track, or
    out-of-plane) to achieve the desired miss distance.

    Args:
        red_tle: TLE of the manoeuvring satellite.
        blue_tle: TLE of the conjunction partner (for reference orbit).
        manoeuvre_start: Assumed TCA epoch.
        desired_miss_km: Required miss distance (km).
        time_before_tca_s: How far before TCA to execute the burn (seconds).
        coast_s: Additional coast offset (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_tca = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_tca)
    sv_blue = blue_orbit.propagate(t_tca)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0
    plan = collision_avoidance(r_ref, desired_miss_km, time_before_tca_s, mu)

    t_burn = t_tca - timedelta(seconds=time_before_tca_s)
    sv_red_burn = red_orbit.propagate(t_burn)

    # Build ΔV vector in the best strategy direction
    v_hat = sv_red_burn.v / sv_red_burn.v_mag
    h = np.cross(sv_red_burn.r, sv_red_burn.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    best = plan.best
    if best.strategy == "radial":
        dv_vec = b_hat * best.delta_v
    elif best.strategy == "along_track":
        dv_vec = v_hat * best.delta_v
    else:  # out_of_plane
        dv_vec = n_hat * best.delta_v

    burn1 = _make_burn(1, t_burn, dv_vec, sv_red_burn)

    _notes = (
        f"COLA {best.strategy}: ΔV={best.delta_v:.4f} km/s → "
        f"{desired_miss_km:.1f} km miss, "
        f"burn {time_before_tca_s / 60:.0f} min before TCA. "
        f"Alternatives: radial={plan.radial.delta_v:.4f}, "
        f"along-track={plan.along_track.delta_v:.4f}, "
        f"out-of-plane={plan.out_of_plane.delta_v:.4f} km/s"
    )

    return InterceptSolution(
        method="cola",
        burns=[burn1],
        total_delta_v=best.delta_v,
        departure_epoch=t_burn,
        arrival_epoch=t_tca,
        miss_distance_km=desired_miss_km,
    )


def geo_drift_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    drift_time_days: float | None = None,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """GEO longitude relocation via drift orbit.

    Red = satellite at current position, Blue = satellite at target longitude.
    Computes the drift orbit SMA and ΔV for east-west relocation.

    Args:
        red_tle: TLE of the satellite to relocate.
        blue_tle: TLE of the target position reference.
        manoeuvre_start: When the sequence begins.
        drift_time_days: Desired drift duration (days). None = auto.
        coast_s: Coast before first burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    # Compute subsatellite longitudes (approximate — use atan2 of x,y in ECI)
    # For GEO, the ECI longitude rotates with Earth; we use the angular
    # separation between the two position vectors projected onto the equatorial plane.
    lon_red = math.degrees(math.atan2(sv_red.r[1], sv_red.r[0]))
    lon_blue = math.degrees(math.atan2(sv_blue.r[1], sv_blue.r[0]))
    gap = lon_blue - lon_red
    if gap > 180:
        gap -= 360
    elif gap < -180:
        gap += 360

    result = geo_drift(gap, drift_time_days, mu)
    result.current_longitude_deg = lon_red
    result.target_longitude_deg = lon_blue

    t_arrival = t_departure + timedelta(days=result.drift_time_days)

    # Burn 1: enter drift orbit (prograde or retrograde)
    v_hat = sv_red.v / sv_red.v_mag
    sign = 1.0 if gap > 0 else -1.0
    dv1_vec = v_hat * result.delta_v_start * sign
    burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

    # Burn 2: stop drift (symmetric)
    sv_red_arr = red_orbit.propagate(t_arrival)
    v_hat_arr = sv_red_arr.v / sv_red_arr.v_mag
    dv2_vec = v_hat_arr * result.delta_v_stop * (-sign)
    burn2 = _make_burn(2, t_arrival, dv2_vec, sv_red_arr)

    return InterceptSolution(
        method="geo_drift",
        burns=[burn1, burn2],
        total_delta_v=result.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        score=abs(gap),
        score_kind="longitude gap (deg)",
    )


def manoeuvre_detect_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Classify an observed manoeuvre from two TLE epochs.

    Uses red_tle as the 'before' state and blue_tle as the 'after' state
    of the SAME satellite. Compares orbital elements to estimate the
    manoeuvre type, ΔV, and burn direction.

    Args:
        red_tle: TLE before the manoeuvre (earlier epoch).
        blue_tle: TLE after the manoeuvre (later epoch).
        manoeuvre_start: Analysis epoch.
        coast_s: Offset (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_before = red_orbit.propagate(t_epoch)
    sv_after = blue_orbit.propagate(t_epoch)

    kep_before = state_to_keplerian(sv_before)
    kep_after = state_to_keplerian(sv_after)

    # KeplerianElements angles are already degrees. They were passed through
    # degrees() again here, under a local alias the static guard could not
    # see, so TLE noise read as a plane change 57x too costly (audit F-001).
    #
    # Both element sets are taken at t_epoch, so SGP4 has already carried each
    # node through its J2 precession and no drift separates them: the elapsed
    # time is zero. This passed the gap between the TLE epochs (a day when
    # they matched), which subtracted the drift a second time; the magnitude
    # arithmetic that F-023 removed happened to hide it.
    result = classify_manoeuvre(
        kep_before.a, kep_before.ecc, kep_before.inc, kep_before.raan,
        kep_after.a, kep_after.ecc, kep_after.inc, kep_after.raan,
        0.0, mu,
    )

    # Build a zero-burn solution with classification info
    v_hat = sv_before.v / sv_before.v_mag
    dv_vec = v_hat * result.estimated_delta_v
    burn1 = _make_burn(1, t_epoch, dv_vec, sv_before)

    return InterceptSolution(
        method="manoeuvre_detect",
        burns=[burn1] if result.estimated_delta_v > 1e-6 else [],
        total_delta_v=result.estimated_delta_v,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        score=result.branch_score * 100.0,
        score_kind="detection score (fixed per classification branch)",
        provenance="heuristic",
    )


def nmc_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    along_track_km: float = 2.0,
    cross_track_km: float = 0.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Establish a passively safe relative orbit (NMC) around the target.

    A bounded Clohessy-Wiltshire ellipse centred on the target passes through
    any relative position: from (x0, y0) it needs xd = n y0 / 2 and
    yd = -2 n x0, and has along-track amplitude 2 sqrt(x0^2 + y0^2 / 4). The
    burn is the change from red's actual relative velocity to that one, and
    the reported margin is the closest approach flown over one orbit. An
    insertion point whose ellipse is not the size requested (within 10 per
    cent) is refused: reaching the requested ellipse needs an approach first,
    which this method does not plan.

    The previous wrapper built a radial burn from wherever red was, which from
    a co-located start passes through the target once per orbit, and labelled
    it with the along-track cost and a positive margin (audit F-017).

    Args:
        red_tle: TLE of the inspector/manoeuvring satellite.
        blue_tle: TLE of the target satellite.
        manoeuvre_start: When the sequence begins.
        along_track_km: Desired along-track amplitude (km).
        cross_track_km: Desired cross-track amplitude (km).
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.

    Raises:
        ValueError: when the ellipse through red's position is not the one
            requested, including when red is co-located with the target.
    """
    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    state, n, _, _ = _initial_hill_state(red_tle, blue_tle, t_departure)

    along_amp = 2.0 * math.hypot(state.x, state.y / 2.0)
    if abs(along_amp - along_track_km) > _NMC_SIZE_TOLERANCE * along_track_km:
        raise ValueError(
            f"red is {state.x:.2f} km radial and {state.y:.2f} km along-track of the "
            f"target, on the {along_amp:.2f} km ellipse, not the requested "
            f"{along_track_km:.2f} km one; approach to an insertion point first"
        )

    cross_amp = max(cross_track_km, abs(state.z))
    target = CWState(
        x=state.x, y=state.y, z=state.z,
        xd=n * state.y / 2.0,
        yd=-2.0 * n * state.x,
        zd=n * math.sqrt(cross_amp**2 - state.z**2),
    )
    dv_hill = np.array([target.xd - state.xd, target.yd - state.yd, target.zd - state.zd])

    sv_blue = TLEOrbit(blue_tle).propagate(t_departure)
    dv_vec = _eci_to_hill_matrix(sv_blue.r, sv_blue.v).T @ dv_hill
    sv_red = TLEOrbit(red_tle).propagate(t_departure)
    burn1 = _make_burn(1, t_departure, dv_vec, sv_red)

    period_s = 2.0 * math.pi / n
    closest = min(
        math.sqrt(p.x**2 + p.y**2 + p.z**2)
        for p in (_cw_propagate(target, n, period_s * k / _NMC_SAMPLES) for k in range(_NMC_SAMPLES))
    )

    return InterceptSolution(
        method="nmc",
        burns=[burn1],
        total_delta_v=burn1.delta_v_mag,
        departure_epoch=t_departure,
        arrival_epoch=t_departure + timedelta(seconds=period_s),
        miss_distance_km=closest,
    )


def detectability_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    tof_s: float = 21600.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a Lambert intercept and assess its detectability.

    Runs a standard Lambert intercept and then evaluates how detectable
    the manoeuvre would be by ground-based space surveillance. The
    observability score (0-100, heuristic) is in ``score``; the miss distance
    stays the Lambert solution's.

    Args:
        red_tle: TLE of the interceptor.
        blue_tle: TLE of the target.
        manoeuvre_start: When the sequence begins.
        tof_s: Time of flight (seconds).
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    # First compute the intercept
    sol = lambert_intercept(red_tle, blue_tle, manoeuvre_start, tof_s, coast_s, mu=mu)

    # Assess detectability
    red_orbit = TLEOrbit(red_tle)
    t_dep = manoeuvre_start + timedelta(seconds=coast_s)
    sv = red_orbit.propagate(t_dep)
    altitude = sv.r_mag - 6378.137

    det = detectability_metric(sol.total_delta_v, altitude, "lambert")

    sol.method = "detectability"
    sol.score = det.observability_score * 100.0
    sol.score_kind = "observability score"
    sol.provenance = "heuristic"

    return sol


def evasion_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    desired_miss_km: float = 10.0,
    time_before_tca_s: float = 3600.0,
    fuel_budget_km_s: float = 0.5,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Plan a defensive evasion burn against the incoming threat.

    The BLUE satellite evades an incoming RED threat. ``optimal_evasion``
    sizes candidate burns (prograde, normal and radial, at several lead times)
    from a Clohessy-Wiltshire model of BLUE's own orbit. Each candidate, and
    its reverse, is then flown: BLUE's displacement at TCA under two-body
    motion is added to its predicted position and measured against RED's
    predicted position. The cheapest candidate that reaches the desired miss
    is chosen; if none does within the budget, the one that opens the widest
    miss. The reported miss is that achieved separation.

    Args:
        red_tle: TLE of the incoming threat.
        blue_tle: TLE of the satellite to defend.
        manoeuvre_start: Predicted TCA epoch.
        desired_miss_km: Target miss distance (km).
        time_before_tca_s: Available warning time (seconds).
        fuel_budget_km_s: Maximum ΔV available (km/s).
        coast_s: Additional offset (seconds).
        mu: Gravitational parameter.
    """
    blue_orbit = TLEOrbit(blue_tle)
    red_orbit = TLEOrbit(red_tle)

    t_tca = manoeuvre_start + timedelta(seconds=coast_s)
    sv_blue = blue_orbit.propagate(t_tca)
    separation_at_tca = sv_blue.r - red_orbit.propagate(t_tca).r

    plan = optimal_evasion(sv_blue.r_mag, desired_miss_km, time_before_tca_s, fuel_budget_km_s, mu)

    flown = [
        _fly_evasion(blue_orbit, t_tca, (candidate, sense), separation_at_tca, mu)
        for candidate in plan.strategies or [plan.best]
        for sense in (1.0, -1.0)
    ]
    enough = [f for f in flown if f[1] >= desired_miss_km]
    burn1, miss = min(enough, key=lambda f: f[0].delta_v_mag) if enough else max(flown, key=lambda f: f[1])

    return InterceptSolution(
        method="evasion",
        burns=[burn1],
        total_delta_v=burn1.delta_v_mag,
        departure_epoch=burn1.epoch,
        arrival_epoch=t_tca,
        miss_distance_km=miss,
    )


def _fly_evasion(
    blue_orbit: TLEOrbit,
    t_tca: datetime,
    option: tuple[EvasionResult, float],
    separation_at_tca: np.ndarray,
    mu: float,
) -> tuple[Burn, float]:
    """Apply one evasion candidate, in the given sense, and return the burn and its miss.

    The burn's effect is taken as the difference between two two-body coasts
    from the same state, with and without the burn, so the propagator's own
    model error cancels and only the displacement is added to the prediction.
    """
    candidate, sense = option
    t_burn = t_tca - timedelta(seconds=candidate.burn_epoch_offset_s)
    sv = blue_orbit.propagate(t_burn)
    v_hat = sv.v / sv.v_mag
    h = np.cross(sv.r, sv.v)
    n_hat = h / float(np.linalg.norm(h))
    b_hat = np.cross(v_hat, n_hat)
    dv = sense * (v_hat * candidate.prograde_dv + n_hat * candidate.normal_dv + b_hat * candidate.radial_dv)

    displacement = _coast(sv, dv, t_tca, mu).r - _coast(sv, np.zeros(3), t_tca, mu).r
    miss = float(np.linalg.norm(separation_at_tca + displacement))
    return _make_burn(1, t_burn, dv, sv), miss


def intent_predict_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Assess adversary intercept intent from relative orbital geometry.

    Red = potential threat, Blue = asset to defend.
    Propagates both to the analysis epoch, computes relative geometry,
    and scores against known intercept profiles.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    sv_blue = blue_orbit.propagate(t_epoch)

    kep_red = state_to_keplerian(sv_red)
    kep_blue = state_to_keplerian(sv_blue)

    delta_a = kep_blue.a - kep_red.a
    delta_inc = kep_blue.inc - kep_red.inc
    delta_raan = kep_blue.raan - kep_red.raan
    if delta_raan > 180:
        delta_raan -= 360
    elif delta_raan < -180:
        delta_raan += 360

    rel_r = sv_blue.r - sv_red.r
    relative_range = float(np.linalg.norm(rel_r))
    rel_v = sv_blue.v - sv_red.v
    range_rate = float(np.dot(rel_r, rel_v)) / max(relative_range, 1e-10)

    is_coplanar = abs(delta_inc) < 1.0 and abs(delta_raan) < 5.0

    result = assess_intercept_intent(
        delta_a, delta_inc, delta_raan,
        relative_range, range_rate, is_coplanar, mu,
    )

    # A zero-burn solution; the indicator score travels in score
    return InterceptSolution(
        method="intent_predict",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        score=result.indicator_score * 100.0,
        score_kind="intent indicator score",
        provenance="heuristic",
    )


def intercept_envelope_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    tof_s: float = 172800.0,
    coast_s: float = 0.0,
    max_delta_v_km_s: float = 0.5,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Sweep arrival times for the cheapest intercept inside a ΔV budget.

    Propagates red once, then solves Lambert's problem against blue at 24
    arrival times spread evenly across *tof_s*, and reports the cheapest arc
    costing no more than *max_delta_v_km_s*.

    The sweep reports that minimum and a count of feasible arrival times, not
    the envelope itself. No view in the interface draws an envelope, so the
    per-step points were built 24 times a call and dropped unread;
    ``intercept_envelope_analytical`` still returns a full points list for a
    caller that ever needs one.

    Args:
        red_tle: TLE of the interceptor (red) satellite.
        blue_tle: TLE of the target (blue) satellite.
        manoeuvre_start: UTC time when the manoeuvre sequence begins.
        tof_s: Widest time of flight to sweep (seconds), floored at one hour.
        coast_s: Coast time before the sweep begins (seconds).
        max_delta_v_km_s: The operator's ΔV budget (km/s). This replaces a
            parameter named ``target_distance_km``, a distance, which the
            sweep had stopped reading in favour of a hardcoded 3.0 km/s: six
            times the 500 m/s the operator's form offers, and a budget they
            neither chose nor could see. The default mirrors that 500 m/s.
        mu: Gravitational parameter (km³/s²).

    Returns:
        :class:`InterceptSolution` whose ``total_delta_v`` is the cheapest
        feasible arc and whose ``miss_distance_km`` carries the number of
        feasible arrival times rather than a miss distance.

    Raises:
        ValueError: if no arrival time in the sweep is reachable within
            budget. Returning zero ΔV instead made an unreachable intercept
            the cheapest row of the operator's comparison table, which ranks
            ascending on cost. The batch runner catches this, keeps the row,
            shows the message and sorts the row behind every assessment.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)

    # A true Lambert sweep, which is what this function's description always
    # claimed and never did. It previously called the radius-only analytic
    # estimate, throwing away the full state vectors it holds: the angular
    # separation, which dominates a co-orbital intercept, never entered the
    # calculation. Measured against real Lambert solutions that estimate was
    # between 1.3x and 121x optimistic, and underestimating an intercept cost
    # is the dangerous direction for both threat assessment and planning.
    #
    # The budget is a delta-V in km/s and now arrives as one. It was first
    # taken from a parameter named target_distance_km, a distance, and then
    # from a hardcoded 3.0 km/s once that parameter went dead, so the
    # operator's "Max dV" field reached this sweep in neither form.
    tof_max_s = max(tof_s, 3600.0)

    n_steps = 24
    feasible = 0
    min_feasible_tof_h = float("inf")
    min_feasible_dv = float("inf")

    for index in range(n_steps):
        tof = tof_max_s * (index + 1) / n_steps
        arrival = t_epoch + timedelta(seconds=tof)
        try:
            sv_target = blue_orbit.propagate(arrival)
            solution = cheapest_lambert(
                sv_red.r, sv_target.r, tof,
                mu=mu, v1_initial=sv_red.v, v2_target=sv_target.v,
            )
        except (ValueError, RuntimeError):
            # A degenerate geometry or an unreachable time of flight is not a
            # cheap intercept; it is no intercept. Dropping the step keeps it
            # out of the feasible count rather than letting a gap in the sweep
            # read as an easy option.
            continue
        dv = solution.total_delta_v
        if dv <= max_delta_v_km_s:
            feasible += 1
            min_feasible_tof_h = min(min_feasible_tof_h, tof / 3600.0)
            min_feasible_dv = min(min_feasible_dv, dv)

    if not feasible:
        # Raising is what makes the ranked table honest: a zero here was read
        # as free and sorted ahead of every real assessment.
        raise ValueError(
            f"No intercept within the {max_delta_v_km_s:.3f} km/s budget: none of "
            f"{n_steps} arrival times swept across {tof_max_s / 3600.0:.1f} h "
            "is reachable"
        )

    return InterceptSolution(
        method="intercept_envelope",
        burns=[],
        total_delta_v=min_feasible_dv,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch + timedelta(hours=min_feasible_tof_h),
        score=float(feasible),
        score_kind="feasible solutions",
    )


def stability_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Analyse relative motion stability between two satellites.

    Computes the CW relative state and assesses whether the motion
    is bounded (non-drifting) or secular (drifting).
    """
    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)

    # The CW boundedness test needs the relative velocity in the ROTATING Hill
    # frame. Projecting the inertial difference onto the axes, as this did,
    # omits the omega x r term, so a truly bounded state with a 1 km radial
    # offset read as drifting by 3 pi km per orbit (audit F-006). The Hill
    # state is built in one place, with the correction, and reused here.
    state, n, _range_km, _ecc = _initial_hill_state(red_tle, blue_tle, t_epoch)
    r_ref = (mu / n**2) ** (1.0 / 3.0)

    result = relative_motion_stability(
        r_ref, state.x, state.y, state.z, state.xd, state.yd, state.zd, mu,
    )

    return InterceptSolution(
        method="stability",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        score=result.stability_score * 100.0,
        score_kind="stability score",
        provenance="heuristic",
    )


def fingerprint_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Fingerprint an observed manoeuvre against known behaviour profiles.

    Uses red_tle as 'before' and blue_tle as 'after' state of the same
    satellite, similar to manoeuvre_detect but classifies against
    spacecraft behaviour archetypes.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_before = red_orbit.propagate(t_epoch)
    sv_after = blue_orbit.propagate(t_epoch)

    kep_before = state_to_keplerian(sv_before)
    kep_after = state_to_keplerian(sv_after)

    # Estimate ΔV and burn direction from element changes
    da = kep_after.a - kep_before.a
    di = kep_after.inc - kep_before.inc
    dv_est = abs(da) * math.sqrt(mu / kep_before.a**3) / 2.0  # vis-viva approx

    if abs(di) > 0.1:
        direction = "normal"
    elif da > 0:
        direction = "prograde"
    elif da < 0:
        direction = "retrograde"
    else:
        direction = "combined"

    altitude = kep_before.a - R_EARTH

    result = fingerprint_manoeuvre(
        dv_est, direction, altitude,
        kep_before.inc, kep_before.ecc,
    )

    return InterceptSolution(
        method="fingerprint",
        burns=[],
        total_delta_v=dv_est,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        score=result.match_score * 100.0,
        score_kind="fingerprint match score",
        provenance="heuristic",
    )


def formation_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    desired_miss_km: float = 5.0,
    tof_s: float = 3600.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute a formation-aware defensive burn.

    Blue satellite evades red threat while assessing impact on
    formation geometry.

    The burn is sized by ``formation_defence_burn`` from blue's own orbit
    alone: *red_tle* is accepted for the common intercept signature but the
    threat's state is not modelled, unlike ``evasion_intercept``. Its radius
    was passed in and never read (audit F-078).
    """
    blue_orbit = TLEOrbit(blue_tle)

    t_tca = manoeuvre_start + timedelta(seconds=coast_s)
    sv_blue = blue_orbit.propagate(t_tca)

    result = formation_defence_burn(sv_blue.r_mag, tof_s, desired_miss_km, mu=mu)

    t_burn = t_tca - timedelta(seconds=tof_s)
    sv_blue_burn = blue_orbit.propagate(t_burn)

    # Build ΔV vector
    v_hat = sv_blue_burn.v / sv_blue_burn.v_mag
    h = np.cross(sv_blue_burn.r, sv_blue_burn.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    if result.burn_direction == "along_track":
        dv_vec = v_hat * result.delta_v
    elif result.burn_direction == "radial":
        dv_vec = b_hat * result.delta_v
    else:
        dv_vec = n_hat * result.delta_v

    burn1 = _make_burn(1, t_burn, dv_vec, sv_blue_burn)

    return InterceptSolution(
        method="formation",
        burns=[burn1],
        total_delta_v=result.delta_v,
        departure_epoch=t_burn,
        arrival_epoch=t_tca,
        miss_distance_km=result.resulting_miss_km,
    )


def terrain_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Map the orbital terrain (risk assessment) for both satellites.

    Returns risk assessment for the red satellite's orbital regime.
    """
    red_orbit = TLEOrbit(red_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    kep_red = state_to_keplerian(sv_red)

    altitude = kep_red.a - R_EARTH
    result = orbital_terrain(altitude, kep_red.inc)

    return InterceptSolution(
        method="terrain",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        score=result.operational_risk_score * 100.0,
        score_kind="operational risk score",
        provenance="heuristic",
    )


def min_time_intercept_wrapper(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    max_delta_v: float = 3.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Find the earliest arrival at blue reachable within a ΔV budget.

    Solves Lambert's problem from red's departure state to blue's propagated
    position at arrival times spread across one red orbital period, takes the
    first arrival whose two-burn cost is within *max_delta_v* (km/s), and
    refines it by bisection to a second.

    This replaces an analytic vis-viva search whose clamp made ΔV independent
    of the time of flight, so it always returned 1 % of the Hohmann time at
    less than Hohmann cost: LEO to GEO in 190 s (audit F-004).

    Raises:
        ValueError: no single-revolution transfer within the budget arrives
            inside one red period. The search is the earliest arrival, so it
            is held to one period on the zero-revolution arc; a transfer
            making complete revolutions always arrives later.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    period_s = 2.0 * math.pi * math.sqrt(state_to_keplerian(sv_red).a ** 3 / mu)

    def solve(tof: float) -> tuple[LambertSolution, StateVector] | None:
        sv_target = blue_orbit.propagate(t_epoch + timedelta(seconds=tof))
        try:
            sol = solve_lambert(
                sv_red.r, sv_target.r, tof,
                mu=mu, v1_initial=sv_red.v, v2_target=sv_target.v,
            )
        except ValueError:
            # A degenerate or unreachable geometry is no intercept at this time.
            return None
        return sol, sv_target

    def feasible(tof: float) -> tuple[LambertSolution, StateVector] | None:
        found = solve(tof)
        return found if found is not None and found[0].total_delta_v <= max_delta_v else None

    steps = 96
    previous = 0.0
    best: tuple[float, tuple[LambertSolution, StateVector]] | None = None
    for index in range(1, steps + 1):
        tof = period_s * index / steps
        hit = feasible(tof)
        if hit is not None:
            best = (tof, hit)
            break
        previous = tof
    if best is None:
        raise ValueError(
            f"no single-revolution intercept within {max_delta_v * 1000.0:.0f} m/s "
            f"arrives inside one orbital period ({period_s / 3600.0:.1f} h)"
        )

    # Bisect between the last infeasible and the first feasible arrival time,
    # keeping the upper bound feasible so the answer is always flyable.
    lo, (hi, hit) = previous, best
    while hi - lo > 1.0:
        mid = 0.5 * (lo + hi)
        trial = feasible(mid)
        if trial is None:
            lo = mid
        else:
            hi, hit = mid, trial

    sol, sv_target = hit
    t_arrival = t_epoch + timedelta(seconds=hi)
    burn1 = _make_burn(1, t_epoch, sol.delta_v1, sv_red)
    burn2 = _make_burn(2, t_arrival, sol.delta_v2, sv_target)

    return InterceptSolution(
        method="min_time",
        burns=[burn1, burn2],
        total_delta_v=sol.total_delta_v,
        departure_epoch=t_epoch,
        arrival_epoch=t_arrival,
        miss_distance_km=0.0,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coast(sv: StateVector, dv: np.ndarray, until: datetime, mu: float) -> StateVector:
    """Apply *dv* to *sv* and propagate two-body to *until*."""
    r, v = propagate_two_body(sv.r, sv.v + dv, (until - sv.epoch).total_seconds(), mu)
    return StateVector(epoch=until, r=r, v=v)


def _separation(sv: StateVector, target: TLEOrbit) -> float:
    """Distance (km) from *sv* to *target* at the same epoch."""
    return float(np.linalg.norm(sv.r - target.propagate(sv.epoch).r))

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
