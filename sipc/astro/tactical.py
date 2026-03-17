"""Tactical manoeuvre solvers for space control operations.

Implements operational manoeuvres beyond classical orbital transfers:
  - Phasing orbit (period-adjustment rendezvous after N revolutions)
  - CW relative motion (Hill/Clohessy-Wiltshire radial separation & along-track drift)
  - Plane change (inclination change, combined altitude + inclination)
  - J2 drift planning (RAAN precession exploitation)
  - Minimum-ΔV collision avoidance (radial / in-track / out-of-plane)
  - GEO drift orbit (longitude relocation, graveyard transfer)
  - Manoeuvre classification (detect manoeuvre type from orbital element changes)
  - Natural Motion Circumnavigation / passive safety ellipse
  - Intercept detectability metric
  - Optimal defensive evasion manoeuvre

All functions operate on orbital radii/elements directly. TLE-level wrappers
live in ``sipc.astro.maneuvers``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sipc.astro.constants import GEO_RADIUS, J2_EARTH, MU_EARTH, R_EARTH, SIDEREAL_DAY


# ═══════════════════════════════════════════════════════════════════════════
#  1. Phasing Orbit
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PhasingResult:
    """Result of a phasing orbit manoeuvre."""

    phase_angle_deg: float    # angular separation to close
    n_revolutions: int        # number of phasing revolutions
    phasing_sma_km: float     # semi-major axis of phasing orbit
    phasing_period_s: float   # period of phasing orbit
    delta_v_1: float          # km/s — enter phasing orbit
    delta_v_2: float          # km/s — return to original orbit
    total_delta_v: float      # km/s
    time_to_intercept_s: float  # total wait time


def phasing_orbit(
    r_chaser: float,
    r_target: float,
    phase_angle_deg: float,
    n_revolutions: int = 1,
    mu: float = MU_EARTH,
) -> PhasingResult:
    """Compute a phasing manoeuvre to close an angular gap.

    The chaser adjusts its orbital period so that after *n_revolutions*
    it arrives at the target's current angular position.

    Args:
        r_chaser: Radius of chaser orbit (km, assumed circular).
        r_target: Radius of target orbit (km, assumed circular).
        phase_angle_deg: Angular separation to close (degrees, positive = target ahead).
        n_revolutions: Number of phasing revolutions.
        mu: Gravitational parameter.
    """
    phase_rad = math.radians(phase_angle_deg)
    T_target = 2.0 * math.pi * math.sqrt(r_target**3 / mu)

    # Total time = N complete target revolutions
    total_time = n_revolutions * T_target

    # Chaser must complete N revolutions + phase_angle fraction in total_time
    # (if target is ahead, chaser needs a faster/lower orbit)
    n_chaser_revs = n_revolutions + phase_rad / (2.0 * math.pi)
    T_phase = total_time / n_chaser_revs

    # Semi-major axis of phasing orbit from period
    a_phase = (mu * (T_phase / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)

    # ΔV to enter/exit phasing orbit (at chaser radius)
    v_chaser = math.sqrt(mu / r_chaser)
    v_phase_at_r = math.sqrt(mu * (2.0 / r_chaser - 1.0 / a_phase))
    dv1 = abs(v_phase_at_r - v_chaser)
    dv2 = dv1  # symmetric return burn

    return PhasingResult(
        phase_angle_deg=phase_angle_deg,
        n_revolutions=n_revolutions,
        phasing_sma_km=a_phase,
        phasing_period_s=T_phase,
        delta_v_1=dv1,
        delta_v_2=dv2,
        total_delta_v=dv1 + dv2,
        time_to_intercept_s=total_time,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  2. CW Relative Motion (Hill / Clohessy-Wiltshire)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CWResult:
    """Result of a Clohessy-Wiltshire relative motion manoeuvre."""

    delta_v_radial: float      # km/s — radial (x) impulse
    delta_v_along_track: float  # km/s — along-track (y) impulse
    delta_v_cross_track: float  # km/s — cross-track (z) impulse
    total_delta_v: float       # km/s
    radial_sep_km: float       # resulting radial separation
    along_track_sep_km: float  # resulting along-track separation
    cross_track_sep_km: float  # resulting cross-track separation
    time_s: float              # evaluation time
    method: str = ""           # "radial", "along_track", "combined"


def cw_radial_separation(
    r_ref: float,
    desired_radial_km: float,
    time_s: float,
    mu: float = MU_EARTH,
) -> CWResult:
    """Compute ΔV for desired radial separation using CW equations.

    Pure radial impulse at t=0, evaluate separation at *time_s*.

    CW free-response from zero initial position, impulse [Δvx, 0, 0]::

        x(t) = (Δvx / n) sin(nt)
        y(t) = -(2 Δvx / n)(1 - cos(nt))

    Args:
        r_ref: Reference orbit radius (km).
        desired_radial_km: Desired radial separation (km).
        time_s: Time after impulse to evaluate (seconds).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    nt = n * time_s
    sin_nt = math.sin(nt)

    if abs(sin_nt) < 1e-12:
        # Singularity — at integer multiples of orbital period
        raise ValueError(
            f"Cannot achieve radial separation at t={time_s:.0f}s "
            f"(sin(nt) ≈ 0 — choose a different time)"
        )

    dv_x = desired_radial_km * n / sin_nt

    # Along-track drift caused by radial impulse
    y_drift = -2.0 * dv_x / n * (1.0 - math.cos(nt))

    return CWResult(
        delta_v_radial=dv_x,
        delta_v_along_track=0.0,
        delta_v_cross_track=0.0,
        total_delta_v=abs(dv_x),
        radial_sep_km=desired_radial_km,
        along_track_sep_km=y_drift,
        cross_track_sep_km=0.0,
        time_s=time_s,
        method="radial",
    )


def cw_along_track_drift(
    r_ref: float,
    desired_drift_km: float,
    time_s: float,
    mu: float = MU_EARTH,
) -> CWResult:
    """Compute ΔV for desired along-track displacement using CW equations.

    Pure along-track impulse at t=0, evaluate at *time_s*.

    CW free-response from zero initial position, impulse [0, Δvy, 0]::

        x(t) = (2 Δvy / n)(1 - cos(nt))
        y(t) = Δvy (4 sin(nt) - 3nt) / n

    Args:
        r_ref: Reference orbit radius (km).
        desired_drift_km: Desired along-track displacement (km).
        time_s: Time after impulse to evaluate (seconds).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    nt = n * time_s
    coeff = (4.0 * math.sin(nt) - 3.0 * nt) / n

    if abs(coeff) < 1e-12:
        raise ValueError(
            f"Cannot achieve along-track drift at t={time_s:.0f}s "
            f"(transfer coefficient ≈ 0)"
        )

    dv_y = desired_drift_km / coeff

    # Radial oscillation caused by along-track impulse
    x_osc = 2.0 * dv_y / n * (1.0 - math.cos(nt))

    return CWResult(
        delta_v_radial=0.0,
        delta_v_along_track=dv_y,
        delta_v_cross_track=0.0,
        total_delta_v=abs(dv_y),
        radial_sep_km=x_osc,
        along_track_sep_km=desired_drift_km,
        cross_track_sep_km=0.0,
        time_s=time_s,
        method="along_track",
    )


def cw_combined(
    r_ref: float,
    desired_radial_km: float,
    desired_along_track_km: float,
    time_s: float,
    mu: float = MU_EARTH,
) -> CWResult:
    """Compute combined radial + along-track impulse for desired separation.

    Solves the 2×2 CW system for [Δvx, Δvy] to achieve both radial and
    along-track targets simultaneously::

        x(t) = (sin(nt)/n) Δvx + (2(1 - cos(nt))/n) Δvy = x_des
        y(t) = (-2(1 - cos(nt))/n) Δvx + ((4sin(nt) - 3nt)/n) Δvy = y_des

    Args:
        r_ref: Reference orbit radius (km).
        desired_radial_km: Target radial separation (km).
        desired_along_track_km: Target along-track separation (km).
        time_s: Evaluation time (seconds).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    nt = n * time_s
    sin_nt = math.sin(nt)
    cos_nt = math.cos(nt)

    # CW transfer matrix coefficients (position from velocity)
    a11 = sin_nt / n
    a12 = 2.0 * (1.0 - cos_nt) / n
    a21 = -2.0 * (1.0 - cos_nt) / n
    a22 = (4.0 * sin_nt - 3.0 * nt) / n

    det = a11 * a22 - a12 * a21
    if abs(det) < 1e-15:
        raise ValueError(
            f"CW system is singular at t={time_s:.0f}s — "
            f"choose a different evaluation time"
        )

    # Solve via Cramer's rule
    dv_x = (desired_radial_km * a22 - desired_along_track_km * a12) / det
    dv_y = (a11 * desired_along_track_km - a21 * desired_radial_km) / det

    return CWResult(
        delta_v_radial=dv_x,
        delta_v_along_track=dv_y,
        delta_v_cross_track=0.0,
        total_delta_v=math.sqrt(dv_x**2 + dv_y**2),
        radial_sep_km=desired_radial_km,
        along_track_sep_km=desired_along_track_km,
        cross_track_sep_km=0.0,
        time_s=time_s,
        method="combined",
    )


# ═══════════════════════════════════════════════════════════════════════════
#  3. Plane Change & Combined Transfer
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PlaneChangeResult:
    """Result of a plane-change manoeuvre."""

    delta_v_at_node: float      # km/s — ΔV if performed at equatorial node
    delta_v_at_apogee: float    # km/s — ΔV if performed at apogee
    optimal_location: str       # "node" or "apogee"
    optimal_delta_v: float      # km/s — cheapest option
    inclination_change_deg: float
    method: str = "plane_change"


@dataclass
class CombinedTransferResult:
    """Result of a combined altitude + inclination change."""

    delta_v_1: float           # km/s — first burn
    delta_v_2: float           # km/s — second burn
    total_delta_v: float       # km/s
    transfer_time_s: float     # seconds
    inclination_change_deg: float
    altitude_change_km: float
    method: str = "combined_plane_change"


def plane_change(
    r: float,
    inclination_change_deg: float,
    ecc: float = 0.0,
    mu: float = MU_EARTH,
) -> PlaneChangeResult:
    """Compute ΔV for a pure inclination change.

    Evaluates cost at the equatorial node (circular velocity) and at
    apogee (slower velocity, cheaper plane change).

    Args:
        r: Orbit radius or semi-major axis (km).
        inclination_change_deg: Desired inclination change (degrees).
        ecc: Orbital eccentricity (0 for circular).
        mu: Gravitational parameter.
    """
    di = math.radians(inclination_change_deg)

    # At equatorial node (circular or periapsis velocity)
    v_node = math.sqrt(mu / r)
    dv_node = 2.0 * v_node * math.sin(di / 2.0)

    # At apogee (if eccentric)
    r_apo = r * (1.0 + ecc)
    a = r if ecc == 0.0 else r  # r is SMA when ecc > 0
    v_apo = math.sqrt(mu * (2.0 / r_apo - 1.0 / a)) if ecc > 0 else v_node
    dv_apogee = 2.0 * v_apo * math.sin(di / 2.0)

    if dv_apogee <= dv_node:
        optimal = "apogee"
        optimal_dv = dv_apogee
    else:
        optimal = "node"
        optimal_dv = dv_node

    return PlaneChangeResult(
        delta_v_at_node=dv_node,
        delta_v_at_apogee=dv_apogee,
        optimal_location=optimal,
        optimal_delta_v=optimal_dv,
        inclination_change_deg=inclination_change_deg,
    )


def combined_altitude_plane_change(
    r1: float,
    r2: float,
    inclination_change_deg: float,
    mu: float = MU_EARTH,
) -> CombinedTransferResult:
    """Combined altitude change + plane change in a Hohmann-like transfer.

    The plane change is split across both burns using the cosine rule,
    which is more efficient than performing them separately.

    Strategy: perform all inclination change at the slower burn point
    (typically at the higher-altitude burn), combined with the Hohmann impulse.

    Args:
        r1: Initial orbit radius (km).
        r2: Target orbit radius (km).
        inclination_change_deg: Desired inclination change (degrees).
        mu: Gravitational parameter.
    """
    di = math.radians(inclination_change_deg)
    a_t = (r1 + r2) / 2.0

    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)
    v_t_p = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t))  # at periapsis of transfer
    v_t_a = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t))  # at apoapsis of transfer

    if r2 > r1:
        # Raising orbit: plane change at apogee (burn 2) is cheaper
        dv1 = abs(v_t_p - v1)  # prograde only
        # Combined plane change + circularise at r2
        dv2 = math.sqrt(v2**2 + v_t_a**2 - 2.0 * v2 * v_t_a * math.cos(di))
    else:
        # Lowering orbit: plane change at departure (burn 1) is cheaper
        dv1 = math.sqrt(v1**2 + v_t_p**2 - 2.0 * v1 * v_t_p * math.cos(di))
        dv2 = abs(v2 - v_t_a)  # prograde only

    t_transfer = math.pi * math.sqrt(a_t**3 / mu)

    return CombinedTransferResult(
        delta_v_1=dv1,
        delta_v_2=dv2,
        total_delta_v=dv1 + dv2,
        transfer_time_s=t_transfer,
        inclination_change_deg=inclination_change_deg,
        altitude_change_km=r2 - r1,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  4. J2 Drift Planner
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class J2DriftResult:
    """Result of a J2 RAAN drift analysis."""

    raan_rate_chaser_deg_day: float   # deg/day — chaser's natural rate
    raan_rate_target_deg_day: float   # deg/day — target's natural rate
    differential_rate_deg_day: float  # deg/day — convergence rate
    delta_raan_deg: float             # current RAAN gap
    convergence_time_days: float      # days to natural alignment (0 if diverging)
    accel_altitude_change_km: float   # altitude change to double convergence rate
    accel_convergence_days: float     # convergence time after altitude change
    accel_delta_v: float              # km/s — ΔV for the altitude change
    method: str = "j2_drift"


def j2_raan_rate(
    a: float,
    ecc: float,
    inc_deg: float,
    mu: float = MU_EARTH,
    r_earth: float = R_EARTH,
    j2: float = J2_EARTH,
) -> float:
    """Compute secular J2 RAAN precession rate in degrees per day.

    dΩ/dt = -3/2 · n · J2 · (R_E / p)² · cos(i)

    Args:
        a: Semi-major axis (km).
        ecc: Eccentricity.
        inc_deg: Inclination (degrees).
        mu: Gravitational parameter.
        r_earth: Earth radius (km).
        j2: J2 coefficient.
    """
    p = a * (1.0 - ecc**2)  # semi-latus rectum
    n = math.sqrt(mu / a**3)  # mean motion (rad/s)
    inc = math.radians(inc_deg)

    rate_rad_s = -1.5 * n * j2 * (r_earth / p) ** 2 * math.cos(inc)
    return math.degrees(rate_rad_s) * 86400.0  # → deg/day


def j2_drift_plan(
    a_chaser: float,
    ecc_chaser: float,
    inc_chaser_deg: float,
    a_target: float,
    ecc_target: float,
    inc_target_deg: float,
    delta_raan_deg: float,
    mu: float = MU_EARTH,
) -> J2DriftResult:
    """Plan RAAN alignment via natural J2 precession.

    Computes time for natural convergence and the altitude change
    that would accelerate it.

    Args:
        a_chaser: Chaser semi-major axis (km).
        ecc_chaser: Chaser eccentricity.
        inc_chaser_deg: Chaser inclination (degrees).
        a_target: Target semi-major axis (km).
        ecc_target: Target eccentricity.
        inc_target_deg: Target inclination (degrees).
        delta_raan_deg: Current RAAN difference (degrees, positive = chaser east of target).
        mu: Gravitational parameter.
    """
    rate_c = j2_raan_rate(a_chaser, ecc_chaser, inc_chaser_deg, mu)
    rate_t = j2_raan_rate(a_target, ecc_target, inc_target_deg, mu)
    diff_rate = rate_c - rate_t  # deg/day

    # Natural convergence time
    if abs(diff_rate) < 1e-10:
        conv_days = float("inf")
    else:
        conv_days = -delta_raan_deg / diff_rate
        if conv_days < 0:
            conv_days = (360.0 - abs(delta_raan_deg)) / abs(diff_rate)

    # Compute altitude change to double convergence rate
    # Strategy: lower/raise chaser by Δa to increase differential rate
    # For prograde orbits (inc < 90°), lower altitude → faster (more negative) RAAN rate
    delta_a = -50.0 if inc_chaser_deg < 90.0 else 50.0  # km, heuristic step
    a_new = a_chaser + delta_a
    rate_c_new = j2_raan_rate(a_new, ecc_chaser, inc_chaser_deg, mu)
    diff_rate_new = rate_c_new - rate_t

    if abs(diff_rate_new) < 1e-10:
        accel_days = float("inf")
    else:
        accel_days = -delta_raan_deg / diff_rate_new
        if accel_days < 0:
            accel_days = (360.0 - abs(delta_raan_deg)) / abs(diff_rate_new)

    # ΔV to change altitude by delta_a (Hohmann-like)
    v_old = math.sqrt(mu / a_chaser)
    a_transfer = (a_chaser + a_new) / 2.0
    v_transfer = math.sqrt(mu * (2.0 / a_chaser - 1.0 / a_transfer))
    accel_dv = abs(v_transfer - v_old)

    return J2DriftResult(
        raan_rate_chaser_deg_day=rate_c,
        raan_rate_target_deg_day=rate_t,
        differential_rate_deg_day=diff_rate,
        delta_raan_deg=delta_raan_deg,
        convergence_time_days=conv_days,
        accel_altitude_change_km=delta_a,
        accel_convergence_days=accel_days,
        accel_delta_v=accel_dv,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  5. Minimum-ΔV Collision Avoidance
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CollisionAvoidanceResult:
    """Result of a minimum-ΔV collision avoidance analysis."""

    strategy: str             # "radial", "along_track", "out_of_plane"
    delta_v: float            # km/s — required ΔV
    miss_distance_km: float   # resulting miss distance
    time_before_tca_s: float  # how far before TCA the burn is applied
    method: str = "collision_avoidance"


@dataclass
class CollisionAvoidancePlan:
    """Complete collision avoidance analysis with all three strategies."""

    best: CollisionAvoidanceResult
    radial: CollisionAvoidanceResult
    along_track: CollisionAvoidanceResult
    out_of_plane: CollisionAvoidanceResult
    total_delta_v: float      # km/s — ΔV of the best strategy


def collision_avoidance(
    r_ref: float,
    desired_miss_km: float,
    time_before_tca_s: float,
    mu: float = MU_EARTH,
) -> CollisionAvoidancePlan:
    """Compute minimum-ΔV collision avoidance using three strategies.

    For each strategy, computes the impulse applied *time_before_tca_s*
    before the predicted time of closest approach (TCA) that produces
    the desired miss distance.

    Uses linearised CW equations to translate ΔV into displacement
    at the TCA epoch.

    Args:
        r_ref: Reference orbit radius at conjunction (km).
        desired_miss_km: Required miss distance (km).
        time_before_tca_s: How far before TCA to apply the burn (seconds).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    nt = n * time_before_tca_s
    sin_nt = math.sin(nt)
    cos_nt = math.cos(nt)

    # Radial strategy: pure radial ΔV → radial displacement at TCA
    # x(t) = (Δvx / n) sin(nt)
    if abs(sin_nt) > 1e-12:
        dv_radial = desired_miss_km * n / abs(sin_nt)
    else:
        dv_radial = float("inf")

    # Along-track strategy: pure along-track ΔV → along-track displacement at TCA
    # y(t) = Δvy (4 sin(nt) - 3nt) / n
    coeff_y = abs(4.0 * sin_nt - 3.0 * nt) / n
    if coeff_y > 1e-12:
        dv_along_track = desired_miss_km / coeff_y
    else:
        dv_along_track = float("inf")

    # Out-of-plane strategy: pure cross-track ΔV → cross-track displacement at TCA
    # z(t) = (Δvz / n) sin(nt)
    if abs(sin_nt) > 1e-12:
        dv_oop = desired_miss_km * n / abs(sin_nt)
    else:
        dv_oop = float("inf")

    radial = CollisionAvoidanceResult(
        strategy="radial",
        delta_v=dv_radial,
        miss_distance_km=desired_miss_km,
        time_before_tca_s=time_before_tca_s,
    )
    along_track = CollisionAvoidanceResult(
        strategy="along_track",
        delta_v=dv_along_track,
        miss_distance_km=desired_miss_km,
        time_before_tca_s=time_before_tca_s,
    )
    out_of_plane = CollisionAvoidanceResult(
        strategy="out_of_plane",
        delta_v=dv_oop,
        miss_distance_km=desired_miss_km,
        time_before_tca_s=time_before_tca_s,
    )

    # Pick cheapest strategy
    candidates = [radial, along_track, out_of_plane]
    best = min(candidates, key=lambda c: c.delta_v)

    return CollisionAvoidancePlan(
        best=best,
        radial=radial,
        along_track=along_track,
        out_of_plane=out_of_plane,
        total_delta_v=best.delta_v,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  6. GEO Drift Orbit
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class GeoDriftResult:
    """Result of a GEO longitude relocation via drift orbit."""

    current_longitude_deg: float
    target_longitude_deg: float
    longitude_gap_deg: float
    drift_sma_km: float          # SMA of drift orbit
    drift_rate_deg_day: float    # longitude drift rate
    delta_v_start: float         # km/s — enter drift orbit
    delta_v_stop: float          # km/s — circularise at target longitude
    total_delta_v: float         # km/s
    drift_time_days: float       # duration of drift phase
    method: str = "geo_drift"


def geo_drift(
    longitude_gap_deg: float,
    drift_time_days: float | None = None,
    mu: float = MU_EARTH,
) -> GeoDriftResult:
    """Plan GEO longitude relocation via a drift orbit.

    Changes the satellite's semi-major axis slightly to induce an
    east-west drift, then re-circularises at the target longitude.

    The drift rate is related to SMA offset by::

        dλ/dt = -3/2 · n_geo · Δa / a_geo

    Args:
        longitude_gap_deg: Target − current longitude (degrees, positive = east).
        drift_time_days: Desired drift duration (days). If None, defaults to
                         ~1°/day drift rate (minimum 1 day).
        mu: Gravitational parameter.
    """
    a_geo = GEO_RADIUS
    n_geo = 2.0 * math.pi / SIDEREAL_DAY  # rad/s

    if drift_time_days is None:
        drift_time_days = max(abs(longitude_gap_deg) / 1.0, 1.0)

    # Required drift rate (deg/day)
    drift_rate = longitude_gap_deg / drift_time_days
    drift_rate_rad_s = math.radians(drift_rate) / 86400.0

    # Required SMA change: Δa = -2/3 · (dλ/dt) · a_geo / n_geo
    delta_a = -2.0 / 3.0 * drift_rate_rad_s * a_geo / n_geo
    drift_sma = a_geo + delta_a

    # ΔV to enter/exit drift orbit (symmetric Hohmann-like)
    v_geo = math.sqrt(mu / a_geo)
    v_drift = math.sqrt(mu * (2.0 / a_geo - 1.0 / drift_sma))
    dv = abs(v_drift - v_geo)

    return GeoDriftResult(
        current_longitude_deg=0.0,  # filled by wrapper
        target_longitude_deg=longitude_gap_deg,
        longitude_gap_deg=longitude_gap_deg,
        drift_sma_km=drift_sma,
        drift_rate_deg_day=drift_rate,
        delta_v_start=dv,
        delta_v_stop=dv,
        total_delta_v=2.0 * dv,
        drift_time_days=drift_time_days,
    )


@dataclass
class GraveyardTransferResult:
    """Result of a GEO → graveyard orbit transfer."""

    r_geo: float
    r_graveyard: float
    delta_v_1: float      # km/s — boost from GEO
    delta_v_2: float      # km/s — circularise at graveyard
    total_delta_v: float   # km/s
    transfer_time_s: float
    method: str = "graveyard_transfer"


def graveyard_transfer(
    graveyard_altitude_km: float = 300.0,
    mu: float = MU_EARTH,
) -> GraveyardTransferResult:
    """Compute ΔV for a GEO → graveyard orbit transfer.

    Standard end-of-life disposal: Hohmann transfer to GEO + 300 km.

    Args:
        graveyard_altitude_km: Altitude above GEO (km, default 300).
        mu: Gravitational parameter.
    """
    r1 = GEO_RADIUS
    r2 = GEO_RADIUS + graveyard_altitude_km
    a_t = (r1 + r2) / 2.0

    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)
    v_t_p = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t))
    v_t_a = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t))

    dv1 = abs(v_t_p - v1)
    dv2 = abs(v2 - v_t_a)
    t_transfer = math.pi * math.sqrt(a_t**3 / mu)

    return GraveyardTransferResult(
        r_geo=r1,
        r_graveyard=r2,
        delta_v_1=dv1,
        delta_v_2=dv2,
        total_delta_v=dv1 + dv2,
        transfer_time_s=t_transfer,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  7. Manoeuvre Classification Engine
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ManoeuvreClassification:
    """Result of classifying an observed manoeuvre from orbital element changes."""

    manoeuvre_type: str         # "altitude_change", "plane_change", "phasing",
                               # "station_keeping", "combined", "unknown"
    estimated_delta_v: float   # km/s — estimated total ΔV
    burn_direction: str        # "prograde", "retrograde", "normal", "radial", "combined"
    delta_a_km: float          # change in SMA
    delta_ecc: float           # change in eccentricity
    delta_inc_deg: float       # change in inclination
    delta_raan_deg: float      # change in RAAN
    confidence: float          # 0.0–1.0
    notes: str = ""
    method: str = "manoeuvre_detect"


def classify_manoeuvre(
    a1: float, ecc1: float, inc1_deg: float, raan1_deg: float,
    a2: float, ecc2: float, inc2_deg: float, raan2_deg: float,
    dt_s: float,
    mu: float = MU_EARTH,
) -> ManoeuvreClassification:
    """Classify an observed manoeuvre from two sets of orbital elements.

    Compares before/after Keplerian elements and estimates the manoeuvre
    type, ΔV, and burn direction. Used for space intelligence — detecting
    what an adversary satellite did between TLE epochs.

    Args:
        a1, ecc1, inc1_deg, raan1_deg: Before-manoeuvre elements.
        a2, ecc2, inc2_deg, raan2_deg: After-manoeuvre elements.
        dt_s: Time between observations (seconds).
        mu: Gravitational parameter.
    """
    da = a2 - a1
    de = ecc2 - ecc1
    di = abs(inc2_deg - inc1_deg)
    draan = abs(raan2_deg - raan1_deg)
    if draan > 180.0:
        draan = 360.0 - draan

    # Estimate ΔV from each element change
    v1 = math.sqrt(mu / a1)
    v2 = math.sqrt(mu / a2)

    # Altitude change ΔV (vis-viva approximation)
    dv_altitude = abs(v2 - v1) if abs(da) > 1.0 else 0.0

    # Plane change ΔV
    dv_plane = 2.0 * v1 * math.sin(math.radians(di) / 2.0) if di > 0.01 else 0.0

    # RAAN change ΔV (approximation — only valid for non-J2 manoeuvres)
    # Subtract expected J2 drift to isolate manoeuvre-induced RAAN change
    expected_j2_raan = abs(j2_raan_rate(a1, ecc1, inc1_deg, mu) * dt_s / 86400.0)
    raan_residual = max(0.0, draan - expected_j2_raan)
    dv_raan = 2.0 * v1 * math.sin(math.radians(raan_residual) / 2.0) if raan_residual > 0.01 else 0.0

    total_dv = math.sqrt(dv_altitude**2 + dv_plane**2 + dv_raan**2)

    # Classify
    has_altitude = abs(da) > 5.0        # > 5 km SMA change
    has_plane = di > 0.05               # > 0.05° inclination change
    has_raan = raan_residual > 0.05     # > 0.05° RAAN residual
    has_ecc = abs(de) > 0.001           # eccentricity change

    # Determine burn direction
    if has_altitude and not has_plane:
        direction = "prograde" if da > 0 else "retrograde"
    elif has_plane and not has_altitude:
        direction = "normal"
    elif has_altitude and has_plane:
        direction = "combined"
    elif has_ecc:
        direction = "radial"
    else:
        direction = "combined"

    # Determine manoeuvre type
    if total_dv < 0.001:
        mtype = "station_keeping"
        confidence = 0.3
    elif has_altitude and not has_plane and not has_raan:
        mtype = "altitude_change"
        confidence = 0.85
    elif has_plane and not has_altitude:
        mtype = "plane_change"
        confidence = 0.85
    elif has_raan and not has_altitude and not has_plane:
        mtype = "raan_change"
        confidence = 0.7
    elif has_altitude and has_plane:
        mtype = "combined"
        confidence = 0.75
    elif has_ecc and abs(da) < 5.0:
        mtype = "phasing"
        confidence = 0.6
    else:
        mtype = "unknown"
        confidence = 0.3

    notes_parts = []
    if has_altitude:
        notes_parts.append(f"Δa={da:+.1f} km")
    if has_plane:
        notes_parts.append(f"Δi={di:.3f}°")
    if has_raan:
        notes_parts.append(f"ΔRAAN={raan_residual:.3f}° (J2-corrected)")
    if has_ecc:
        notes_parts.append(f"Δe={de:+.5f}")

    return ManoeuvreClassification(
        manoeuvre_type=mtype,
        estimated_delta_v=total_dv,
        burn_direction=direction,
        delta_a_km=da,
        delta_ecc=de,
        delta_inc_deg=inc2_deg - inc1_deg,
        delta_raan_deg=raan2_deg - raan1_deg,
        confidence=confidence,
        notes="; ".join(notes_parts) if notes_parts else "No significant element changes detected",
    )


# ═══════════════════════════════════════════════════════════════════════════
#  8. Natural Motion Circumnavigation / Passive Safety Ellipse
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class NMCResult:
    """Result of a Natural Motion Circumnavigation analysis."""

    radial_amplitude_km: float        # CW x-axis oscillation amplitude
    along_track_amplitude_km: float   # CW y-axis oscillation (2:1 ratio for bounded)
    cross_track_amplitude_km: float   # CW z-axis oscillation amplitude
    period_s: float                   # orbital period of relative motion
    is_passively_safe: bool           # True if no radial zero-crossing
    safety_margin_km: float           # minimum radial distance (>0 = safe)
    delta_v_establish: float          # km/s — ΔV to establish the relative orbit
    total_delta_v: float              # km/s — same as establish (single impulse)
    notes: str = ""
    method: str = "nmc"


def nmc_safety_ellipse(
    r_ref: float,
    along_track_km: float,
    cross_track_km: float = 0.0,
    mu: float = MU_EARTH,
) -> NMCResult:
    """Compute a passively safe Natural Motion Circumnavigation trajectory.

    In CW relative motion, bounded (non-drifting) relative orbits have a
    2:1 along-track to radial amplitude ratio. This function computes the
    CW initial conditions and ΔV to establish such a relative orbit.

    For passive safety, the radial amplitude must be non-zero — if propulsion
    fails, the inspector naturally drifts away from the target rather than
    colliding.

    The CW bounded ellipse (in-plane)::

        x(t) = A_x cos(nt + φ)         — radial
        y(t) = -2 A_x sin(nt + φ)      — along-track (2:1 ratio)

    Args:
        r_ref: Reference orbit radius (km).
        along_track_km: Desired along-track amplitude (km).
                       Radial amplitude = along_track / 2.
        cross_track_km: Desired cross-track oscillation amplitude (km).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    T = 2.0 * math.pi / n

    # CW bounded constraint: A_y = 2 * A_x
    radial_amp = along_track_km / 2.0

    # Safety margin is the minimum radial distance
    # For a centred ellipse, minimum distance = radial amplitude
    # (the ellipse never crosses r=0 if A_x > 0)
    safety_margin = radial_amp
    is_safe = radial_amp > 0.01  # at least 10 metres

    # ΔV to establish: need to impart radial velocity = A_x * n
    # and along-track velocity for bounded motion = 0 (if starting at max radial)
    # Starting from co-located, co-velocity state:
    #   Apply Δvx = A_x * n (radial)
    #   Apply Δvz = A_z * n (cross-track, if any)
    dv_radial = radial_amp * n
    dv_cross = cross_track_km * n if cross_track_km > 0 else 0.0
    dv_total = math.sqrt(dv_radial**2 + dv_cross**2)

    notes_parts = [
        f"Bounded CW ellipse: {radial_amp:.1f}×{along_track_km:.1f} km (R×T)",
    ]
    if cross_track_km > 0:
        notes_parts.append(f"cross-track ±{cross_track_km:.1f} km")
    if is_safe:
        notes_parts.append(f"passively safe (margin {safety_margin:.1f} km)")
    else:
        notes_parts.append("NOT passively safe — radial amplitude too small")

    return NMCResult(
        radial_amplitude_km=radial_amp,
        along_track_amplitude_km=along_track_km,
        cross_track_amplitude_km=cross_track_km,
        period_s=T,
        is_passively_safe=is_safe,
        safety_margin_km=safety_margin,
        delta_v_establish=dv_total,
        total_delta_v=dv_total,
        notes="; ".join(notes_parts),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  9. Intercept Detectability Metric
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DetectabilityResult:
    """Detectability assessment of a manoeuvre by ground-based tracking."""

    delta_v_km_s: float              # ΔV being assessed
    altitude_km: float               # orbital altitude
    delta_v_category: str            # "micro", "small", "medium", "large"
    tracking_detection_prob: float   # 0.0–1.0
    time_to_detection_hours: float   # estimated hours until detection
    observability_score: float       # 0.0–1.0 overall
    notes: str = ""
    method: str = "detectability"


def detectability_metric(
    delta_v_km_s: float,
    altitude_km: float,
    manoeuvre_type: str = "unknown",
) -> DetectabilityResult:
    """Estimate detectability of a manoeuvre by space surveillance.

    Uses empirical rules based on Space Surveillance Network (SSN)
    tracking capabilities and orbital mechanics:
    - Micro-manoeuvres (<1 m/s) are very difficult to detect
    - LEO manoeuvres are detected faster than GEO (denser tracking)
    - Plane changes are more detectable than along-track burns
    - Larger ΔV → faster detection → higher probability

    Args:
        delta_v_km_s: Total ΔV of the manoeuvre (km/s).
        altitude_km: Orbital altitude (km).
        manoeuvre_type: Type of manoeuvre (for refined estimate).
    """
    dv_m_s = delta_v_km_s * 1000.0  # convert to m/s

    # ΔV category
    if dv_m_s < 1.0:
        category = "micro"
    elif dv_m_s < 10.0:
        category = "small"
    elif dv_m_s < 100.0:
        category = "medium"
    else:
        category = "large"

    # Detection probability (sigmoid-like function of ΔV)
    # P = 1 - exp(-k * ΔV) where k depends on altitude regime
    if altitude_km < 2000:  # LEO — dense tracking
        k = 0.5  # per m/s
        base_detection_time = 6.0  # hours
    elif altitude_km < 35786:  # MEO
        k = 0.2
        base_detection_time = 24.0
    else:  # GEO — dedicated tracking but sparse coverage
        k = 0.1
        base_detection_time = 48.0

    detection_prob = 1.0 - math.exp(-k * dv_m_s)

    # Time to detection (inversely proportional to ΔV magnitude)
    if dv_m_s > 0.01:
        time_hours = base_detection_time / math.log2(1.0 + dv_m_s)
    else:
        time_hours = base_detection_time * 100.0  # effectively undetectable

    # Manoeuvre type modifier
    type_modifier = 1.0
    if manoeuvre_type in ("plane_change", "raan_change"):
        type_modifier = 1.3  # plane changes are more obvious (cross-track)
    elif manoeuvre_type in ("phasing", "station_keeping"):
        type_modifier = 0.7  # subtle along-track changes

    detection_prob = min(1.0, detection_prob * type_modifier)

    # Overall observability score (composite)
    observability = 0.4 * detection_prob + 0.3 * min(1.0, dv_m_s / 50.0) + 0.3 * (1.0 - time_hours / (base_detection_time * 10.0))
    observability = max(0.0, min(1.0, observability))

    notes_parts = [
        f"ΔV={dv_m_s:.1f} m/s ({category})",
        f"altitude={altitude_km:.0f} km",
        f"detection P={detection_prob:.0%}",
        f"~{time_hours:.1f} hr to detection",
    ]

    return DetectabilityResult(
        delta_v_km_s=delta_v_km_s,
        altitude_km=altitude_km,
        delta_v_category=category,
        tracking_detection_prob=detection_prob,
        time_to_detection_hours=time_hours,
        observability_score=observability,
        notes="; ".join(notes_parts),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  10. Optimal Defensive Evasion Manoeuvre
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class EvasionResult:
    """Result of an optimal defensive evasion analysis."""

    strategy: str              # "prograde", "retrograde", "normal", "radial", "combined"
    delta_v: float             # km/s — required ΔV
    resulting_miss_km: float   # achieved miss distance
    fuel_used_fraction: float  # fraction of fuel budget consumed
    burn_epoch_offset_s: float # optimal burn time before TCA
    prograde_dv: float         # km/s — V component
    normal_dv: float           # km/s — N component
    radial_dv: float           # km/s — B component
    notes: str = ""
    method: str = "evasion"


@dataclass
class EvasionPlan:
    """Complete evasion analysis with multiple strategies evaluated."""

    best: EvasionResult
    strategies: list[EvasionResult]
    total_delta_v: float       # km/s — ΔV of best strategy
    fuel_budget_km_s: float
    time_to_tca_s: float


def optimal_evasion(
    r_ref: float,
    desired_miss_km: float,
    time_to_tca_s: float,
    fuel_budget_km_s: float = 1.0,
    mu: float = MU_EARTH,
) -> EvasionPlan:
    """Compute the optimal defensive evasion manoeuvre.

    Evaluates multiple burn strategies (prograde, retrograde, normal,
    radial, and combined) at the optimal burn time to maximise miss
    distance while respecting fuel constraints.

    Unlike COLA (which simply achieves a required miss distance),
    the evasion planner:
    - Respects a fuel budget constraint
    - Optimises burn timing (not just direction)
    - Evaluates combined multi-axis burns
    - Reports remaining fuel after the manoeuvre

    Args:
        r_ref: Reference orbit radius (km).
        desired_miss_km: Target miss distance (km).
        time_to_tca_s: Time until predicted conjunction (seconds).
        fuel_budget_km_s: Maximum available ΔV (km/s).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    strategies: list[EvasionResult] = []

    # Evaluate burns at multiple timing offsets to find optimal
    # Test at 25%, 50%, 75%, and 100% of available time
    best_overall: EvasionResult | None = None

    for time_frac in [0.25, 0.5, 0.75, 1.0]:
        t_burn = time_to_tca_s * time_frac
        nt = n * t_burn
        sin_nt = math.sin(nt)
        cos_nt = math.cos(nt)

        # Prograde/retrograde: along-track displacement
        coeff_y = abs(4.0 * sin_nt - 3.0 * nt) / n
        if coeff_y > 1e-12:
            dv_prograde = desired_miss_km / coeff_y
        else:
            dv_prograde = float("inf")

        # Normal: cross-track displacement
        if abs(sin_nt) > 1e-12:
            dv_normal = desired_miss_km * n / abs(sin_nt)
        else:
            dv_normal = float("inf")

        # Radial: radial displacement
        if abs(sin_nt) > 1e-12:
            dv_radial = desired_miss_km * n / abs(sin_nt)
        else:
            dv_radial = float("inf")

        # Combined: split ΔV optimally across axes
        # Allocate budget proportionally to effectiveness
        weights = []
        if coeff_y > 1e-12:
            weights.append(("combined", coeff_y))
        eff_r = abs(sin_nt) / n if abs(sin_nt) > 1e-12 else 0.0
        if eff_r > 1e-12:
            weights.append(("combined_r", eff_r))

        if weights:
            total_eff = sum(w[1] for w in weights)
            # Combined ΔV needed for desired_miss along best axis
            dv_combined = desired_miss_km / total_eff * len(weights)
        else:
            dv_combined = float("inf")

        # Evaluate each strategy at this timing
        candidates = [
            ("prograde" if dv_prograde >= 0 else "retrograde",
             dv_prograde, dv_prograde, 0.0, 0.0),
            ("normal", dv_normal, 0.0, dv_normal, 0.0),
            ("radial", dv_radial, 0.0, 0.0, dv_radial),
        ]

        for name, dv, pro, nor, rad in candidates:
            if dv > fuel_budget_km_s or dv == float("inf"):
                # Exceeds budget — use full budget and compute achieved miss
                if dv == float("inf"):
                    continue
                dv_actual = fuel_budget_km_s
                achieved_miss = desired_miss_km * (dv_actual / dv)
            else:
                dv_actual = dv
                achieved_miss = desired_miss_km

            result = EvasionResult(
                strategy=name,
                delta_v=dv_actual,
                resulting_miss_km=achieved_miss,
                fuel_used_fraction=dv_actual / fuel_budget_km_s if fuel_budget_km_s > 0 else 1.0,
                burn_epoch_offset_s=t_burn,
                prograde_dv=pro if dv_actual == dv else pro * (dv_actual / dv),
                normal_dv=nor if dv_actual == dv else nor * (dv_actual / dv),
                radial_dv=rad if dv_actual == dv else rad * (dv_actual / dv),
                notes=f"Burn {t_burn / 60:.0f} min before TCA, "
                      f"miss={achieved_miss:.1f} km, "
                      f"fuel={dv_actual / fuel_budget_km_s * 100:.0f}%",
            )
            strategies.append(result)

            if best_overall is None or (
                achieved_miss >= desired_miss_km and dv_actual < best_overall.delta_v
            ) or (
                best_overall.resulting_miss_km < desired_miss_km
                and achieved_miss > best_overall.resulting_miss_km
            ):
                best_overall = result

    if best_overall is None:
        # Fallback — no feasible strategy found
        best_overall = EvasionResult(
            strategy="none",
            delta_v=0.0,
            resulting_miss_km=0.0,
            fuel_used_fraction=0.0,
            burn_epoch_offset_s=0.0,
            prograde_dv=0.0,
            normal_dv=0.0,
            radial_dv=0.0,
            notes="No feasible evasion strategy within fuel budget",
        )

    return EvasionPlan(
        best=best_overall,
        strategies=strategies,
        total_delta_v=best_overall.delta_v,
        fuel_budget_km_s=fuel_budget_km_s,
        time_to_tca_s=time_to_tca_s,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  11. Adversary Intercept Intent Predictor
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class IntentAssessment:
    """Assessment of adversary intercept intent."""

    intent_type: str          # co_orbital_intercept, inspection, station_keeping,
                              # repositioning, debris_avoidance, unknown
    likelihood: float         # 0.0–1.0
    risk_level: str           # low, medium, high, critical
    predicted_tca_hours: float  # estimated hours to closest approach (0 = already close)
    evidence: str             # human-readable evidence summary
    method: str = "intent_predict"


def assess_intercept_intent(
    delta_a_km: float,
    delta_inc_deg: float,
    delta_raan_deg: float,
    relative_range_km: float,
    range_rate_km_s: float,
    is_coplanar: bool,
    mu: float = MU_EARTH,
) -> IntentAssessment:
    """Assess whether an adversary satellite is attempting an intercept.

    Scores observed orbital manoeuvres and relative geometry against
    known intercept profiles:
    - Co-orbital phasing (small Δa, coplanar, closing)
    - Plane matching (large Δi toward target plane)
    - Rapid range closure (high closing rate)
    - Inspector approach (small Δa, NMC-like geometry)

    Args:
        delta_a_km: Change in SMA toward target orbit (km, positive = matching).
        delta_inc_deg: Change in inclination toward target (deg).
        delta_raan_deg: RAAN change toward target (deg, J2-corrected).
        relative_range_km: Current range between objects (km).
        range_rate_km_s: Rate of range change (km/s, negative = closing).
        is_coplanar: Whether objects share approximately the same orbital plane.
        mu: Gravitational parameter.
    """
    evidence_parts: list[str] = []
    score = 0.0

    # 1. Closing geometry (most significant indicator)
    is_closing = range_rate_km_s < -0.001
    if is_closing:
        closing_score = min(1.0, abs(range_rate_km_s) / 1.0)  # normalise to 1 km/s
        score += 0.3 * closing_score
        evidence_parts.append(f"closing at {abs(range_rate_km_s):.3f} km/s")

    # 2. Range proximity (closer = more concerning)
    if relative_range_km < 100:
        score += 0.25
        evidence_parts.append(f"range {relative_range_km:.0f} km (proximate)")
    elif relative_range_km < 1000:
        score += 0.15 * (1.0 - relative_range_km / 1000.0)
        evidence_parts.append(f"range {relative_range_km:.0f} km (approaching)")

    # 3. Coplanar matching (needed for intercept)
    if is_coplanar:
        score += 0.15
        evidence_parts.append("coplanar geometry")

    # 4. Altitude matching (Δa → matching target orbit)
    if abs(delta_a_km) > 5.0 and abs(delta_a_km) < 200.0:
        score += 0.1
        evidence_parts.append(f"Δa={delta_a_km:+.1f} km (orbit matching)")

    # 5. Plane matching manoeuvres
    if abs(delta_inc_deg) > 0.05:
        score += 0.1
        evidence_parts.append(f"Δi={delta_inc_deg:.3f}° (plane alignment)")

    if abs(delta_raan_deg) > 0.05:
        score += 0.1
        evidence_parts.append(f"ΔRAAN={delta_raan_deg:.3f}° (node alignment)")

    # Classify intent
    score = min(1.0, score)
    if score > 0.7:
        if relative_range_km < 50 and abs(range_rate_km_s) < 0.01:
            intent = "inspection"
        else:
            intent = "co_orbital_intercept"
        risk = "critical" if score > 0.85 else "high"
    elif score > 0.4:
        intent = "repositioning"
        risk = "medium"
    elif score > 0.15:
        intent = "station_keeping"
        risk = "low"
    else:
        intent = "unknown"
        risk = "low"

    # Predict TCA from range and range rate
    if is_closing and abs(range_rate_km_s) > 1e-6:
        tca_hours = relative_range_km / abs(range_rate_km_s) / 3600.0
    else:
        tca_hours = float("inf")

    return IntentAssessment(
        intent_type=intent,
        likelihood=score,
        risk_level=risk,
        predicted_tca_hours=min(tca_hours, 9999.0),
        evidence="; ".join(evidence_parts) if evidence_parts else "No significant indicators",
    )


# ═══════════════════════════════════════════════════════════════════════════
#  12. Probabilistic Intercept Envelope (analytical approximation)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class EnvelopePoint:
    """One point in an intercept reachability envelope."""

    tof_hours: float
    delta_v_km_s: float
    feasible: bool


@dataclass
class InterceptEnvelopeResult:
    """Probabilistic intercept envelope — all reachable solutions within ΔV budget."""

    max_delta_v_budget: float        # km/s — operator's ΔV budget
    points: list[EnvelopePoint]      # TOF-ΔV pairs across sweep
    feasible_count: int              # number of feasible solutions
    min_feasible_tof_hours: float    # fastest feasible intercept
    min_feasible_dv_km_s: float      # cheapest feasible intercept
    hohmann_dv_km_s: float           # reference Hohmann ΔV
    hohmann_tof_hours: float         # reference Hohmann TOF
    method: str = "intercept_envelope"


def intercept_envelope_analytical(
    r1: float,
    r2: float,
    max_delta_v: float,
    tof_min_hours: float = 0.5,
    tof_max_hours: float = 48.0,
    n_steps: int = 24,
    mu: float = MU_EARTH,
) -> InterceptEnvelopeResult:
    """Compute analytical intercept envelope using energy approximation.

    Sweeps over TOF values and estimates the ΔV required for each
    using a vis-viva energy approach. This gives an approximate
    reachability envelope without needing full Lambert solutions.

    The TLE wrapper does a full Lambert sweep for higher accuracy.

    Args:
        r1: Interceptor orbit radius (km).
        r2: Target orbit radius (km).
        max_delta_v: ΔV budget (km/s).
        tof_min_hours: Minimum TOF to evaluate.
        tof_max_hours: Maximum TOF to evaluate.
        n_steps: Number of TOF samples.
        mu: Gravitational parameter.
    """
    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)

    # Hohmann reference
    a_h = (r1 + r2) / 2.0
    v_h_dep = math.sqrt(mu * (2.0 / r1 - 1.0 / a_h))
    v_h_arr = math.sqrt(mu * (2.0 / r2 - 1.0 / a_h))
    dv_hohmann = abs(v_h_dep - v1) + abs(v2 - v_h_arr)
    tof_hohmann = math.pi * math.sqrt(a_h**3 / mu) / 3600.0

    points: list[EnvelopePoint] = []
    min_feas_tof = float("inf")
    min_feas_dv = float("inf")
    feasible = 0

    dt = (tof_max_hours - tof_min_hours) / max(n_steps - 1, 1)
    for i in range(n_steps):
        tof_h = tof_min_hours + i * dt
        tof_s = tof_h * 3600.0

        # Estimate transfer SMA from TOF (half-orbit approximation)
        # For a 180° transfer: TOF = π√(a³/μ)
        # For shorter transfers, scale approximately
        a_est = (mu * (tof_s / math.pi) ** 2) ** (1.0 / 3.0)
        a_est = max(a_est, (r1 + r2) / 2.0 * 0.8)  # don't go below a reasonable minimum

        # Vis-viva ΔV estimate
        try:
            v_dep = math.sqrt(max(0, mu * (2.0 / r1 - 1.0 / a_est)))
            v_arr = math.sqrt(max(0, mu * (2.0 / r2 - 1.0 / a_est)))
        except (ValueError, ZeroDivisionError):
            v_dep = v1
            v_arr = v2

        dv = abs(v_dep - v1) + abs(v2 - v_arr)

        # Shorter TOFs generally need more ΔV (penalty for fast transfers)
        if tof_h < tof_hohmann:
            penalty = (tof_hohmann / max(tof_h, 0.1)) ** 0.5
            dv = dv * penalty

        is_feasible = dv <= max_delta_v
        points.append(EnvelopePoint(tof_hours=tof_h, delta_v_km_s=dv, feasible=is_feasible))

        if is_feasible:
            feasible += 1
            if tof_h < min_feas_tof:
                min_feas_tof = tof_h
            if dv < min_feas_dv:
                min_feas_dv = dv

    return InterceptEnvelopeResult(
        max_delta_v_budget=max_delta_v,
        points=points,
        feasible_count=feasible,
        min_feasible_tof_hours=min_feas_tof if feasible > 0 else 0.0,
        min_feasible_dv_km_s=min_feas_dv if feasible > 0 else 0.0,
        hohmann_dv_km_s=dv_hohmann,
        hohmann_tof_hours=tof_hohmann,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  13. Relative Motion Stability Analyser
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class StabilityResult:
    """Result of CW relative motion stability analysis."""

    is_bounded: bool                  # True if motion doesn't drift
    radial_amplitude_km: float        # max radial oscillation
    along_track_drift_km_per_orbit: float  # secular along-track drift per orbit
    cross_track_amplitude_km: float   # max cross-track oscillation
    stability_score: float            # 0.0–1.0 (1 = perfectly bounded)
    notes: str
    method: str = "stability"


def relative_motion_stability(
    r_ref: float,
    dx0: float, dy0: float, dz0: float,
    dvx0: float, dvy0: float, dvz0: float,
    mu: float = MU_EARTH,
) -> StabilityResult:
    """Analyse the stability of relative motion using CW state transition matrix.

    Given initial relative state [dx, dy, dz, dvx, dvy, dvz] in the CW frame,
    propagate one orbit and assess whether the motion is bounded or drifting.

    CW boundedness condition: Δvy₀ = -2n·Δx₀  (zero secular drift)

    Args:
        r_ref: Reference orbit radius (km).
        dx0, dy0, dz0: Initial relative position (km) — radial, along-track, cross-track.
        dvx0, dvy0, dvz0: Initial relative velocity (km/s).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_ref**3)
    T = 2.0 * math.pi / n  # orbital period

    # CW boundedness condition: dvy0 + 2*n*dx0 = 0 for no secular drift
    drift_indicator = dvy0 + 2.0 * n * dx0
    secular_drift_per_orbit = 3.0 * math.pi * drift_indicator / n  # km per orbit

    # Radial amplitude: from CW in-plane solution
    # x(t) = (4-3cos(nt))*dx0 + sin(nt)*dvx0/n + 2*(1-cos(nt))*dvy0/n
    # Maximum occurs at specific nt values; estimate from initial conditions
    A_x = math.sqrt(dx0**2 + (dvx0 / n)**2) if n > 0 else abs(dx0)

    # Cross-track amplitude: z(t) = dz0*cos(nt) + dvz0*sin(nt)/n
    A_z = math.sqrt(dz0**2 + (dvz0 / n)**2) if n > 0 else abs(dz0)

    # Stability score
    is_bounded = abs(secular_drift_per_orbit) < 0.1  # < 100m drift per orbit
    if abs(secular_drift_per_orbit) < 0.001:
        stability = 1.0
    elif abs(secular_drift_per_orbit) < 0.1:
        stability = 0.8
    elif abs(secular_drift_per_orbit) < 1.0:
        stability = 0.5
    elif abs(secular_drift_per_orbit) < 10.0:
        stability = 0.2
    else:
        stability = 0.0

    notes_parts = []
    if is_bounded:
        notes_parts.append("bounded (non-drifting) relative motion")
    else:
        notes_parts.append(f"secular drift {secular_drift_per_orbit:.2f} km/orbit")
    notes_parts.append(f"radial ±{A_x:.2f} km, cross-track ±{A_z:.2f} km")
    notes_parts.append(f"drift indicator (Δvy+2nΔx) = {drift_indicator:.4e} km/s")

    return StabilityResult(
        is_bounded=is_bounded,
        radial_amplitude_km=A_x,
        along_track_drift_km_per_orbit=secular_drift_per_orbit,
        cross_track_amplitude_km=A_z,
        stability_score=stability,
        notes="; ".join(notes_parts),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  14. Orbital Manoeuvre Fingerprinting
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FingerprintResult:
    """Result of manoeuvre fingerprinting / behavioural classification."""

    primary_classification: str        # "geo_sk", "inspector", "asat_test",
                                       # "debris_avoidance", "orbit_raising",
                                       # "constellation_maintenance", "unknown"
    probabilities: dict[str, float]    # classification → probability
    confidence: float                  # 0.0–1.0
    signature_summary: str             # human-readable signature
    method: str = "fingerprint"


def fingerprint_manoeuvre(
    delta_v_km_s: float,
    burn_direction: str,
    altitude_km: float,
    inclination_deg: float,
    eccentricity: float,
    repeat_interval_days: float = 0.0,
) -> FingerprintResult:
    """Classify a manoeuvre against known spacecraft behaviour profiles.

    Different spacecraft classes exhibit characteristic manoeuvre signatures.
    This function scores an observed manoeuvre against known profiles:
    - GEO station-keeping: very small ΔV, east-west or north-south
    - Inspector satellite: small ΔV, mixed direction, LEO/GEO
    - ASAT test: large ΔV, often retrograde, altitude-crossing
    - Debris avoidance: small ΔV, along-track, LEO
    - Orbit raising: medium ΔV, prograde, increasing altitude
    - Constellation maintenance: small ΔV, regular interval

    Args:
        delta_v_km_s: Observed ΔV magnitude.
        burn_direction: "prograde", "retrograde", "normal", "radial", "combined".
        altitude_km: Orbital altitude.
        inclination_deg: Orbital inclination.
        eccentricity: Orbital eccentricity.
        repeat_interval_days: Days since last similar manoeuvre (0 = unknown).
    """
    dv_ms = delta_v_km_s * 1000.0  # m/s
    probs: dict[str, float] = {}

    # GEO station-keeping
    geo_score = 0.0
    if 35000 < altitude_km < 37000:
        geo_score += 0.4
        if dv_ms < 5.0:
            geo_score += 0.3
        if burn_direction in ("prograde", "retrograde", "normal"):
            geo_score += 0.1
        if repeat_interval_days > 0 and 10 < repeat_interval_days < 20:
            geo_score += 0.2  # ~14-day SK cycle
    probs["geo_sk"] = min(1.0, geo_score)

    # Inspector satellite
    insp_score = 0.0
    if dv_ms < 50.0:
        insp_score += 0.2
    if burn_direction in ("radial", "combined"):
        insp_score += 0.2
    if eccentricity < 0.01:
        insp_score += 0.1
    if altitude_km < 2000 or 35000 < altitude_km < 37000:
        insp_score += 0.2
    if dv_ms > 0.5 and dv_ms < 20.0:
        insp_score += 0.2  # precision manoeuvre range
    probs["inspector"] = min(1.0, insp_score)

    # ASAT test
    asat_score = 0.0
    if dv_ms > 100.0:
        asat_score += 0.3
    if burn_direction == "retrograde":
        asat_score += 0.3
    if altitude_km < 1500:
        asat_score += 0.2
    if eccentricity > 0.1:
        asat_score += 0.1
    probs["asat_test"] = min(1.0, asat_score)

    # Debris avoidance
    dav_score = 0.0
    if dv_ms < 10.0:
        dav_score += 0.3
    if burn_direction in ("prograde", "retrograde"):
        dav_score += 0.2
    if altitude_km < 1000:
        dav_score += 0.2
    probs["debris_avoidance"] = min(1.0, dav_score)

    # Orbit raising
    raise_score = 0.0
    if burn_direction == "prograde":
        raise_score += 0.3
    if 10.0 < dv_ms < 500.0:
        raise_score += 0.2
    if eccentricity < 0.05:
        raise_score += 0.1
    probs["orbit_raising"] = min(1.0, raise_score)

    # Constellation maintenance
    const_score = 0.0
    if dv_ms < 20.0:
        const_score += 0.2
    if burn_direction in ("prograde", "retrograde"):
        const_score += 0.2
    if repeat_interval_days > 0 and 20 < repeat_interval_days < 180:
        const_score += 0.3
    if 50 < inclination_deg < 100:
        const_score += 0.1
    probs["constellation_maintenance"] = min(1.0, const_score)

    # Select primary
    primary = max(probs, key=probs.get)  # type: ignore[arg-type]
    confidence = probs[primary]

    # If no strong signal, mark unknown
    if confidence < 0.3:
        primary = "unknown"
        confidence = 0.1

    sig = (f"ΔV={dv_ms:.1f} m/s {burn_direction}, "
           f"alt={altitude_km:.0f} km, inc={inclination_deg:.1f}°, "
           f"ecc={eccentricity:.4f}")

    return FingerprintResult(
        primary_classification=primary,
        probabilities=probs,
        confidence=confidence,
        signature_summary=sig,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  15. Formation Defence Solver
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FormationDefenceResult:
    """Result of a formation-aware defensive manoeuvre computation."""

    delta_v: float                # km/s — required ΔV for this asset
    burn_direction: str           # prograde, normal, radial
    resulting_miss_km: float      # achieved miss distance
    formation_impact_km: float    # how much the burn displaces the asset from its slot
    maintains_formation: bool     # True if displacement < formation spacing tolerance
    notes: str
    method: str = "formation"


def formation_defence_burn(
    r_asset: float,
    r_threat: float,
    time_to_tca_s: float,
    desired_miss_km: float,
    formation_spacing_km: float = 50.0,
    mu: float = MU_EARTH,
) -> FormationDefenceResult:
    """Compute a defensive burn that considers formation constraints.

    Similar to COLA, but also assesses the impact on formation geometry.
    The burn should achieve the desired miss distance while keeping the
    asset within its formation slot tolerance.

    Args:
        r_asset: Asset orbit radius (km).
        r_threat: Threat orbit radius at conjunction (km).
        time_to_tca_s: Warning time before conjunction (seconds).
        desired_miss_km: Required miss distance (km).
        formation_spacing_km: Formation slot tolerance (km).
        mu: Gravitational parameter.
    """
    n = math.sqrt(mu / r_asset**3)
    nt = n * time_to_tca_s
    sin_nt = math.sin(nt)

    # Compute cheapest COLA burn
    cola = collision_avoidance(r_asset, desired_miss_km, time_to_tca_s, mu)
    best = cola.best

    # Assess formation impact: how far does the burn displace the asset
    # after one orbital period?
    T = 2.0 * math.pi / n
    if best.strategy == "along_track":
        # Along-track burn causes secular drift
        coeff = abs(4.0 * math.sin(n * T) - 3.0 * n * T) / n
        formation_displacement = best.delta_v * coeff if coeff > 1e-12 else 0.0
    elif best.strategy == "radial":
        # Radial burn causes oscillating displacement
        formation_displacement = best.delta_v / n  # max radial excursion
    else:
        # Out-of-plane: oscillating cross-track
        formation_displacement = best.delta_v / n

    maintains = formation_displacement < formation_spacing_km

    notes = (
        f"{best.strategy} burn: ΔV={best.delta_v:.4f} km/s → "
        f"{desired_miss_km:.1f} km miss, "
        f"formation displacement ±{formation_displacement:.1f} km "
        f"({'within' if maintains else 'EXCEEDS'} {formation_spacing_km:.0f} km tolerance)"
    )

    return FormationDefenceResult(
        delta_v=best.delta_v,
        burn_direction=best.strategy,
        resulting_miss_km=desired_miss_km,
        formation_impact_km=formation_displacement,
        maintains_formation=maintains,
        notes=notes,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  16. Orbital Terrain Mapping
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TerrainAssessment:
    """Risk assessment of an orbital regime."""

    altitude_km: float
    inclination_deg: float
    debris_risk: str           # low, medium, high, extreme
    congestion_level: str      # sparse, moderate, dense, saturated
    radiation_risk: str        # minimal, low, moderate, high, extreme
    transfer_corridor: bool    # True if in a common transfer corridor
    operational_risk_score: float  # 0.0–1.0
    risk_factors: str          # human-readable summary
    method: str = "terrain"


def orbital_terrain(
    altitude_km: float,
    inclination_deg: float,
) -> TerrainAssessment:
    """Map the risk characteristics of an orbital regime.

    Assesses debris density, congestion, radiation, and operational
    risk based on altitude and inclination. Data derived from publicly
    available space surveillance statistics and radiation belt models.

    Risk regions:
    - LEO 200–600 km: moderate debris, high congestion (ISS, constellations)
    - LEO 700–1000 km: highest debris (Fengyun-1C, Cosmos-Iridium collision zones)
    - MEO 2000–20000 km: low debris, Van Allen belt radiation
    - GTO 200–35786 km: transfer corridor, variable debris
    - GEO 35786 km: station-keeping band, high-value targets
    - Super-GEO > 36000 km: graveyard orbits

    Args:
        altitude_km: Orbital altitude above Earth surface (km).
        inclination_deg: Orbital inclination (degrees).
    """
    # Debris risk (based on known debris density bands)
    if 700 <= altitude_km <= 1000:
        debris = "extreme"
        debris_score = 1.0
    elif 400 <= altitude_km <= 700 or 1000 < altitude_km <= 1200:
        debris = "high"
        debris_score = 0.7
    elif 200 <= altitude_km < 400 or 1200 < altitude_km <= 1500:
        debris = "medium"
        debris_score = 0.4
    elif 35500 <= altitude_km <= 36200:
        debris = "medium"  # GEO debris
        debris_score = 0.3
    else:
        debris = "low"
        debris_score = 0.1

    # Sun-synchronous inclination band (97–99°) is heavily congested
    if 96 <= inclination_deg <= 100 and 500 <= altitude_km <= 900:
        debris = "extreme"
        debris_score = max(debris_score, 0.9)

    # Congestion level (based on catalogued objects)
    if 400 <= altitude_km <= 600 and 40 <= inclination_deg <= 60:
        congestion = "saturated"  # ISS corridor, Starlink
    elif 500 <= altitude_km <= 900:
        congestion = "dense"
    elif 35500 <= altitude_km <= 36200:
        congestion = "dense"  # GEO belt
    elif altitude_km < 2000:
        congestion = "moderate"
    else:
        congestion = "sparse"

    congestion_scores = {"sparse": 0.1, "moderate": 0.3, "dense": 0.6, "saturated": 0.9}
    cong_score = congestion_scores[congestion]

    # Radiation risk (Van Allen belts)
    if 1000 <= altitude_km <= 5000:
        radiation = "high"  # inner belt
        rad_score = 0.8
    elif 5000 < altitude_km <= 12000:
        radiation = "extreme"  # slot/outer belt
        rad_score = 1.0
    elif 12000 < altitude_km <= 20000:
        radiation = "high"  # outer belt
        rad_score = 0.7
    elif 20000 < altitude_km <= 35000:
        radiation = "moderate"
        rad_score = 0.3
    else:
        radiation = "minimal"
        rad_score = 0.05

    # Transfer corridor detection
    is_gto = altitude_km > 200 and altitude_km < 36000
    # Near-equatorial + high eccentricity band indicates GTO corridor
    transfer_corridor = is_gto and inclination_deg < 30 and altitude_km > 1000

    # Overall risk score (weighted composite)
    risk_score = 0.4 * debris_score + 0.3 * cong_score + 0.2 * rad_score + 0.1 * (1.0 if transfer_corridor else 0.0)
    risk_score = min(1.0, risk_score)

    factors: list[str] = []
    factors.append(f"debris: {debris}")
    factors.append(f"congestion: {congestion}")
    factors.append(f"radiation: {radiation}")
    if transfer_corridor:
        factors.append("GTO transfer corridor")
    if 96 <= inclination_deg <= 100:
        factors.append("sun-synchronous band")
    if 35500 <= altitude_km <= 36200:
        factors.append("GEO belt")

    return TerrainAssessment(
        altitude_km=altitude_km,
        inclination_deg=inclination_deg,
        debris_risk=debris,
        congestion_level=congestion,
        radiation_risk=radiation,
        transfer_corridor=transfer_corridor,
        operational_risk_score=risk_score,
        risk_factors="; ".join(factors),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  17. Minimum-Time Intercept (analytical approximation)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MinTimeResult:
    """Result of minimum-time intercept search."""

    min_tof_s: float         # minimum feasible TOF (seconds)
    delta_v_km_s: float      # ΔV at minimum TOF
    is_feasible: bool        # True if any solution exists within budget
    max_delta_v_budget: float  # km/s — the ΔV budget used
    hohmann_tof_s: float     # Hohmann TOF for reference
    hohmann_dv_km_s: float   # Hohmann ΔV for reference
    method: str = "min_time"


def min_time_intercept_analytical(
    r1: float,
    r2: float,
    max_delta_v: float,
    mu: float = MU_EARTH,
) -> MinTimeResult:
    """Find the minimum transfer time within a ΔV budget (analytical estimate).

    Uses the vis-viva equation to estimate ΔV as a function of transfer
    SMA, then binary-searches for the smallest TOF that keeps ΔV within
    budget. The TLE wrapper uses full Lambert for higher accuracy.

    Args:
        r1: Interceptor orbit radius (km).
        r2: Target orbit radius (km).
        max_delta_v: ΔV budget (km/s).
        mu: Gravitational parameter.
    """
    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)

    # Hohmann reference
    a_h = (r1 + r2) / 2.0
    tof_h = math.pi * math.sqrt(a_h**3 / mu)
    v_h_dep = math.sqrt(mu * (2.0 / r1 - 1.0 / a_h))
    v_h_arr = math.sqrt(mu * (2.0 / r2 - 1.0 / a_h))
    dv_h = abs(v_h_dep - v1) + abs(v2 - v_h_arr)

    # If Hohmann exceeds budget, not feasible at all
    if dv_h > max_delta_v:
        return MinTimeResult(
            min_tof_s=0.0, delta_v_km_s=dv_h,
            is_feasible=False, max_delta_v_budget=max_delta_v,
            hohmann_tof_s=tof_h, hohmann_dv_km_s=dv_h,
        )

    # Binary search: lower TOF requires higher ΔV
    # Find minimum TOF where ΔV ≤ budget
    lo, hi = tof_h * 0.01, tof_h  # search between 1% and 100% of Hohmann TOF

    for _ in range(50):  # 50 iterations gives ~10⁻¹⁵ precision
        mid = (lo + hi) / 2.0
        # Estimate SMA from TOF (half-orbit approximation)
        a_est = (mu * (mid / math.pi) ** 2) ** (1.0 / 3.0)
        a_est = max(a_est, max(r1, r2))  # can't be smaller than larger orbit

        try:
            v_dep = math.sqrt(max(0, mu * (2.0 / r1 - 1.0 / a_est)))
            v_arr = math.sqrt(max(0, mu * (2.0 / r2 - 1.0 / a_est)))
        except (ValueError, ZeroDivisionError):
            hi = mid
            continue

        dv_est = abs(v_dep - v1) + abs(v2 - v_arr)

        if dv_est <= max_delta_v:
            hi = mid  # can go faster
        else:
            lo = mid  # need more time

    # Final estimate at the converged TOF
    best_tof = hi
    a_final = (mu * (best_tof / math.pi) ** 2) ** (1.0 / 3.0)
    a_final = max(a_final, max(r1, r2))
    try:
        v_dep = math.sqrt(max(0, mu * (2.0 / r1 - 1.0 / a_final)))
        v_arr = math.sqrt(max(0, mu * (2.0 / r2 - 1.0 / a_final)))
    except (ValueError, ZeroDivisionError):
        v_dep = v1
        v_arr = v2
    dv_final = abs(v_dep - v1) + abs(v2 - v_arr)

    return MinTimeResult(
        min_tof_s=best_tof,
        delta_v_km_s=dv_final,
        is_feasible=True,
        max_delta_v_budget=max_delta_v,
        hohmann_tof_s=tof_h,
        hohmann_dv_km_s=dv_h,
    )
