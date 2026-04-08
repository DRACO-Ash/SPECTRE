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
from spectre.astro.lambert import LambertSolution, solve_lambert
from spectre.astro.propagator import StateVector, TLEOrbit, state_to_keplerian
from spectre.astro.tactical import (
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
    intercept_envelope_analytical,
    j2_drift_plan,
    min_time_intercept_analytical,
    nmc_safety_ellipse,
    optimal_evasion,
    orbital_terrain,
    phasing_orbit,
    plane_change,
    relative_motion_stability,
    vbar_hop_sequence,
)
from spectre.astro.transfers import TransferResult, bielliptic, hohmann


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
    kep_blue = state_to_keplerian(sv_blue)

    inc_diff = abs(kep_blue.inc - kep_red.inc)
    r_red = sv_red.r_mag
    r_blue = sv_blue.r_mag
    alt_diff = abs(r_blue - r_red)

    if alt_diff < 50.0:
        # Similar altitude — pure plane change
        pc = plane_change(r_red, math.degrees(inc_diff), kep_red.ecc, mu)

        # Single burn at optimal location, in the normal direction
        h = np.cross(sv_red.r, sv_red.v)
        h_mag = float(np.linalg.norm(h))
        n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
        dv_vec = n_hat * pc.optimal_delta_v
        burn1 = _make_burn(1, t_departure, dv_vec, sv_red)

        t_arrival = t_departure  # instantaneous
        _notes = (
            f"Plane change: Δi={math.degrees(inc_diff):.2f}°, "
            f"optimal at {pc.optimal_location}, "
            f"node ΔV={pc.delta_v_at_node:.4f}, apogee ΔV={pc.delta_v_at_apogee:.4f} km/s"
        )

        return InterceptSolution(
            method="plane_change",
            burns=[burn1],
            total_delta_v=pc.optimal_delta_v,
            departure_epoch=t_departure,
            arrival_epoch=t_arrival,
            miss_distance_km=0.0,
        )
    else:
        # Different altitudes — combined transfer
        cpc = combined_altitude_plane_change(
            r_red, r_blue, math.degrees(inc_diff), mu
        )

        v_hat = sv_red.v / sv_red.v_mag
        h = np.cross(sv_red.r, sv_red.v)
        h_mag = float(np.linalg.norm(h))
        n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)

        # Burn 1: combined prograde + normal
        dv1_vec = v_hat * cpc.delta_v_1 * 0.8 + n_hat * cpc.delta_v_1 * 0.6
        dv1_vec = dv1_vec / float(np.linalg.norm(dv1_vec)) * cpc.delta_v_1
        burn1 = _make_burn(1, t_departure, dv1_vec, sv_red)

        t_arrival = t_departure + timedelta(seconds=cpc.transfer_time_s)
        sv_blue_arr = blue_orbit.propagate(t_arrival)
        v_hat_arr = sv_blue_arr.v / sv_blue_arr.v_mag
        dv2_vec = v_hat_arr * cpc.delta_v_2
        burn2 = _make_burn(2, t_arrival, dv2_vec, sv_blue_arr)

        return InterceptSolution(
            method="plane_change",
            burns=[burn1, burn2],
            total_delta_v=cpc.total_delta_v,
            departure_epoch=t_departure,
            arrival_epoch=t_arrival,
            miss_distance_km=0.0,
        )


def j2_drift_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Analyse J2 RAAN drift for orbital plane alignment.

    Returns an InterceptSolution with one burn representing the
    optional altitude change to accelerate convergence. If the
    satellites are already converging, this may be a zero-ΔV solution.

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
    delta_raan = math.degrees(kep_red.raan - kep_blue.raan)
    if delta_raan > 180.0:
        delta_raan -= 360.0
    elif delta_raan < -180.0:
        delta_raan += 360.0

    result = j2_drift_plan(
        kep_red.a, kep_red.ecc, math.degrees(kep_red.inc),
        kep_blue.a, kep_blue.ecc, math.degrees(kep_blue.inc),
        delta_raan, mu,
    )

    # Build a single burn for the optional altitude adjustment
    v_hat = sv_red.v / sv_red.v_mag
    dv_vec = v_hat * result.accel_delta_v
    burn1 = _make_burn(1, t_epoch, dv_vec, sv_red)

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
        burns=[burn1],
        total_delta_v=result.accel_delta_v,
        departure_epoch=t_epoch,
        arrival_epoch=t_arrival,
        miss_distance_km=abs(delta_raan),
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
    import math as _m
    lon_red = _m.degrees(_m.atan2(sv_red.r[1], sv_red.r[0]))
    lon_blue = _m.degrees(_m.atan2(sv_blue.r[1], sv_blue.r[0]))
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
        miss_distance_km=abs(gap),
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

    # Time between TLE epochs
    import math as _m
    dt_s = abs((blue_orbit._sat.jdsatepoch - red_orbit._sat.jdsatepoch) * 86400.0)
    if dt_s < 1.0:
        dt_s = 86400.0  # default 1 day if epochs are same

    result = classify_manoeuvre(
        kep_before.a, kep_before.ecc, _m.degrees(kep_before.inc), _m.degrees(kep_before.raan),
        kep_after.a, kep_after.ecc, _m.degrees(kep_after.inc), _m.degrees(kep_after.raan),
        dt_s, mu,
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
        miss_distance_km=result.confidence * 100.0,  # encode confidence as "miss" for display
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
    """Compute NMC / passive safety ellipse for proximity operations.

    Determines the ΔV to establish a passively safe relative orbit
    (Natural Motion Circumnavigation) around the target satellite.

    Args:
        red_tle: TLE of the inspector/manoeuvring satellite.
        blue_tle: TLE of the target satellite.
        manoeuvre_start: When the sequence begins.
        along_track_km: Desired along-track amplitude (km).
        cross_track_km: Desired cross-track amplitude (km).
        coast_s: Coast before burn (seconds).
        mu: Gravitational parameter.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_departure = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_departure)
    sv_blue = blue_orbit.propagate(t_departure)

    r_ref = (sv_red.r_mag + sv_blue.r_mag) / 2.0
    nmc = nmc_safety_ellipse(r_ref, along_track_km, cross_track_km, mu)

    t_arrival = t_departure + timedelta(seconds=nmc.period_s)

    # Establish impulse: radial + cross-track components
    v_hat = sv_red.v / sv_red.v_mag
    h = np.cross(sv_red.r, sv_red.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    # Radial impulse for in-plane ellipse + normal for cross-track
    dv_vec = b_hat * nmc.radial_amplitude_km * float(np.sqrt(mu / r_ref**3))
    if cross_track_km > 0:
        dv_vec = dv_vec + n_hat * cross_track_km * float(np.sqrt(mu / r_ref**3))
    burn1 = _make_burn(1, t_departure, dv_vec, sv_red)

    return InterceptSolution(
        method="nmc",
        burns=[burn1],
        total_delta_v=nmc.total_delta_v,
        departure_epoch=t_departure,
        arrival_epoch=t_arrival,
        miss_distance_km=nmc.safety_margin_km,
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
    miss_distance_km field encodes the observability score (0–100).

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

    # Encode detectability info into the solution
    sol.method = "detectability"
    sol.miss_distance_km = det.observability_score * 100.0  # 0–100 scale

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
    """Compute optimal defensive evasion manoeuvre.

    The BLUE satellite evades an incoming RED threat. Unlike COLA
    (which simply achieves a miss distance), the evasion planner
    respects fuel constraints and optimises burn timing/direction.

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

    t_tca = manoeuvre_start + timedelta(seconds=coast_s)
    sv_blue = blue_orbit.propagate(t_tca)

    r_ref = sv_blue.r_mag
    plan = optimal_evasion(r_ref, desired_miss_km, time_before_tca_s, fuel_budget_km_s, mu)

    best = plan.best
    t_burn = t_tca - timedelta(seconds=best.burn_epoch_offset_s)
    sv_blue_burn = blue_orbit.propagate(t_burn)

    # Build ΔV vector from components
    v_hat = sv_blue_burn.v / sv_blue_burn.v_mag
    h = np.cross(sv_blue_burn.r, sv_blue_burn.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    dv_vec = (v_hat * best.prograde_dv +
              n_hat * best.normal_dv +
              b_hat * best.radial_dv)
    burn1 = _make_burn(1, t_burn, dv_vec, sv_blue_burn)

    return InterceptSolution(
        method="evasion",
        burns=[burn1],
        total_delta_v=best.delta_v,
        departure_epoch=t_burn,
        arrival_epoch=t_tca,
        miss_distance_km=best.resulting_miss_km,
    )


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
    delta_inc = math.degrees(kep_blue.inc - kep_red.inc)
    delta_raan = math.degrees(kep_blue.raan - kep_red.raan)
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

    # Encode as zero-burn solution; miss_distance encodes likelihood
    return InterceptSolution(
        method="intent_predict",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        miss_distance_km=result.likelihood * 100.0,
    )


def intercept_envelope_intercept(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    tof_s: float = 172800.0,
    coast_s: float = 0.0,
    target_distance_km: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Compute probabilistic intercept envelope (reachability analysis).

    Sweeps TOF range and estimates ΔV for each, producing an envelope
    of feasible intercept solutions within the operator's ΔV budget.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    sv_blue = blue_orbit.propagate(t_epoch)

    max_dv = target_distance_km if target_distance_km > 0 else 3.0
    tof_max_h = tof_s / 3600.0

    result = intercept_envelope_analytical(
        sv_red.r_mag, sv_blue.r_mag, max_dv,
        tof_max_hours=max(tof_max_h, 1.0), mu=mu,
    )

    return InterceptSolution(
        method="intercept_envelope",
        burns=[],
        total_delta_v=result.min_feasible_dv_km_s,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch + timedelta(hours=result.min_feasible_tof_hours),
        miss_distance_km=result.feasible_count,
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
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    sv_blue = blue_orbit.propagate(t_epoch)

    # Compute relative state in CW frame (centred on blue)
    r_ref = sv_blue.r_mag
    dr = sv_red.r - sv_blue.r
    dv = sv_red.v - sv_blue.v

    # Transform to CW frame (radial, along-track, cross-track)
    v_hat = sv_blue.v / sv_blue.v_mag
    h = np.cross(sv_blue.r, sv_blue.v)
    h_mag = float(np.linalg.norm(h))
    n_hat = h / h_mag if h_mag > 1e-10 else np.array([0, 0, 1], dtype=float)
    b_hat = np.cross(v_hat, n_hat)

    dx0 = float(np.dot(dr, b_hat))   # radial
    dy0 = float(np.dot(dr, v_hat))   # along-track
    dz0 = float(np.dot(dr, n_hat))   # cross-track
    dvx0 = float(np.dot(dv, b_hat))
    dvy0 = float(np.dot(dv, v_hat))
    dvz0 = float(np.dot(dv, n_hat))

    result = relative_motion_stability(r_ref, dx0, dy0, dz0, dvx0, dvy0, dvz0, mu)

    return InterceptSolution(
        method="stability",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        miss_distance_km=result.stability_score * 100.0,
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
    di = math.degrees(kep_after.inc - kep_before.inc)
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
        math.degrees(kep_before.inc), kep_before.ecc,
    )

    return InterceptSolution(
        method="fingerprint",
        burns=[],
        total_delta_v=dv_est,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        miss_distance_km=result.confidence * 100.0,
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
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_tca = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_tca)
    sv_blue = blue_orbit.propagate(t_tca)

    result = formation_defence_burn(
        sv_blue.r_mag, sv_red.r_mag, tof_s, desired_miss_km, mu=mu,
    )

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
    result = orbital_terrain(altitude, math.degrees(kep_red.inc))

    return InterceptSolution(
        method="terrain",
        burns=[],
        total_delta_v=0.0,
        departure_epoch=t_epoch,
        arrival_epoch=t_epoch,
        miss_distance_km=result.operational_risk_score * 100.0,
    )


def min_time_intercept_wrapper(
    red_tle: str,
    blue_tle: str,
    manoeuvre_start: datetime,
    max_delta_v: float = 3.0,
    coast_s: float = 0.0,
    mu: float = MU_EARTH,
) -> InterceptSolution:
    """Find the minimum-time intercept within a ΔV budget.

    Uses analytical vis-viva approximation to binary-search for
    the fastest feasible transfer.
    """
    red_orbit = TLEOrbit(red_tle)
    blue_orbit = TLEOrbit(blue_tle)

    t_epoch = manoeuvre_start + timedelta(seconds=coast_s)
    sv_red = red_orbit.propagate(t_epoch)
    sv_blue = blue_orbit.propagate(t_epoch)

    result = min_time_intercept_analytical(
        sv_red.r_mag, sv_blue.r_mag, max_delta_v, mu,
    )

    t_arrival = t_epoch + timedelta(seconds=result.min_tof_s) if result.is_feasible else t_epoch

    if result.is_feasible:
        # Build approximate departure burn
        v_hat = sv_red.v / sv_red.v_mag
        dv_vec = v_hat * result.delta_v_km_s
        burn1 = _make_burn(1, t_epoch, dv_vec, sv_red)
        burns = [burn1]
    else:
        burns = []

    return InterceptSolution(
        method="min_time",
        burns=burns,
        total_delta_v=result.delta_v_km_s,
        departure_epoch=t_epoch,
        arrival_epoch=t_arrival,
        miss_distance_km=0.0 if result.is_feasible else -1.0,
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
