"""Clohessy-Wiltshire (Hill) relative motion geometry.

Computes the trajectory of a chaser satellite relative to a target in the
Hill/LVLH frame (R-bar/V-bar/H-bar axes) given an intercept solution.

Coordinate convention
---------------------
- x  (R-bar)  : radial outward from Earth centre
- y  (V-bar)  : along-track, positive in velocity direction
- z  (H-bar)  : cross-track, positive in orbit-normal direction

CW equations (linearised, valid for |Δr| ≪ target orbit radius):
    ẍ - 2nẏ - 3n²x = 0
    ÿ + 2nẋ        = 0
    z̈ + n²z       = 0

Closed-form solution (Battin 1999 / Schaub & Junkins 2003):
    x(t) = (4 - 3c)x₀ + s·ẋ₀/n + 2(1 - c)ẏ₀/n
    y(t) = 6(s - nt)x₀ + y₀ - 2(1 - c)ẋ₀/n + (4s - 3nt)ẏ₀/n
    z(t) = z₀c + ż₀s/n
    ẋ(t) = 3ns·x₀ + c·ẋ₀ + 2sẏ₀
    ẏ(t) = 6n(c - 1)x₀ - 2s·ẋ₀ + (4c - 3)ẏ₀
    ż(t) = -z₀ns + ż₀c
where  s = sin(nt),  c = cos(nt).

Security
--------
- All numeric inputs are validated to be finite and within operational bounds.
- Satellite names are sanitised before inclusion in audit log strings.
- No eval/exec of user-supplied data.

Audit
-----
All public calls emit structured log records at INFO level.  Validity warnings
(CW approximation breakdown, large separation, high eccentricity) are logged at
WARNING level with caller context.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NamedTuple

import numpy as np

from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import TLEOrbit, state_to_keplerian

__all__ = [
    "CWState",
    "TrajectoryPoint",
    "RelativeGeometry",
    "RelativeGeometryError",
    "compute_relative_geometry",
]

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Maximum separation for which CW is considered a good approximation.
_CW_RANGE_WARN_KM: float = 500.0
# Eccentricity above which the target orbit deviates significantly from circular.
_ECC_WARN_THRESHOLD: float = 0.05
# TOF ceiling (hours) — CW secular drift accumulates at long times.
_TOF_WARN_HOURS: float = 6.0
# Minimum mean motion (rad/s) — prevent divide-by-zero for deep-space objects.
_N_MIN_RAD_S: float = 1e-6
# Number of points to generate per trajectory segment.
_N_POINTS: int = 120
# Hard cap on ΔV components (km/s) — flag implausible values.
_DV_HARD_CAP_KM_S: float = 20.0
# Hard cap on initial separation (km).
_RANGE_HARD_CAP_KM: float = 100_000.0


class RelativeGeometryError(ValueError):
    """Raised when geometry computation cannot proceed due to invalid inputs."""


# ── Data structures ────────────────────────────────────────────────────────────

class CWState(NamedTuple):
    """State in the Hill (CW) frame.

    All positions in km, all velocities in km/s.
    """
    x: float    # R-bar (radial)
    y: float    # V-bar (along-track)
    z: float    # H-bar (cross-track)
    xd: float   # ẋ km/s
    yd: float   # ẏ km/s
    zd: float   # ż km/s


@dataclass
class TrajectoryPoint:
    """Single point on the relative trajectory."""
    t_s: float       # elapsed seconds from burn epoch
    x_km: float      # R-bar
    y_km: float      # V-bar
    z_km: float      # H-bar
    range_km: float  # 3-D range to target (origin)


@dataclass
class RelativeGeometry:
    """Full relative geometry result, ready for charting.

    Attributes
    ----------
    method : str
        Transfer method label (e.g. "hohmann", "lambert").
    red_name : str
        Sanitised name of the chaser (red) satellite.
    blue_name : str
        Sanitised name of the target (blue) satellite.
    n_rad_s : float
        Mean motion used for CW propagation (rad/s).
    initial_range_km : float
        Range between chaser and target at burn epoch.
    tof_hours : float
        Total time of flight in hours.
    dv_total_ms : float
        Total ΔV in m/s.
    burn_epoch : datetime
        UTC epoch of the first burn.
    cw_valid : bool
        True when CW approximation is expected to be reliable.
    validity_notes : list[str]
        Human-readable warnings about approximation quality.
    coast_points : list[TrajectoryPoint]
        Pre-burn trajectory (empty if coast_s == 0).
    transfer_points : list[TrajectoryPoint]
        Post-burn trajectory from burn to arrival.
    burn_state : CWState
        CW state immediately after the burn (with ΔV applied).
    arrival_range_km : float
        Range at end of propagation (should be ~0 for a valid intercept).
    """
    method: str
    red_name: str
    blue_name: str
    n_rad_s: float
    initial_range_km: float
    tof_hours: float
    dv_total_ms: float
    burn_epoch: datetime
    cw_valid: bool
    validity_notes: list[str]
    coast_points: list[TrajectoryPoint]
    transfer_points: list[TrajectoryPoint]
    burn_state: CWState
    arrival_range_km: float
    # Chart-ready series — (V-bar, R-bar) and (H-bar, R-bar) pairs
    vr_coast:    list[tuple[float, float]] = field(default_factory=list)
    vr_transfer: list[tuple[float, float]] = field(default_factory=list)
    hr_coast:    list[tuple[float, float]] = field(default_factory=list)
    hr_transfer: list[tuple[float, float]] = field(default_factory=list)
    # Range-vs-time series — (t_s, range_km) pairs
    range_series: list[tuple[float, float]] = field(default_factory=list)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _sanitise_name(name: str) -> str:
    """Strip non-printable characters; truncate to 64 chars for log safety."""
    return "".join(ch for ch in name if ch.isprintable())[:64]


def _validate_finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise RelativeGeometryError(f"{name} is not finite: {value!r}")
    return value


def _eci_to_hill_matrix(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Return the 3×3 rotation matrix from ECI (TEME) to Hill (RIC) frame.

    Parameters
    ----------
    r : ndarray shape (3,)
        Position vector of the target in ECI (km).
    v : ndarray shape (3,)
        Velocity vector of the target in ECI (km/s).

    Returns
    -------
    R : ndarray shape (3, 3)
        Each row is one unit basis vector of the Hill frame expressed in ECI.
        Row 0 → R̂ (radial), Row 1 → V̂ (in-track), Row 2 → Ĥ (cross-track).
    """
    r_hat = r / np.linalg.norm(r)
    h_vec = np.cross(r, v)
    h_hat = h_vec / np.linalg.norm(h_vec)
    v_hat = np.cross(h_hat, r_hat)  # right-hand: Ĥ × R̂ = V̂
    return np.array([r_hat, v_hat, h_hat], dtype=float)


def _cw_propagate(state: CWState, n: float, dt: float) -> CWState:
    """Propagate a CW state forward by dt seconds.

    Uses the exact closed-form Hill equations.  Valid for the linearised
    two-body problem with a circular reference orbit.
    """
    nt = n * dt
    s = math.sin(nt)
    c = math.cos(nt)

    x0, y0, z0 = state.x, state.y, state.z
    xd0, yd0, zd0 = state.xd, state.yd, state.zd

    x  = (4.0 - 3.0 * c) * x0 + s * xd0 / n + 2.0 * (1.0 - c) * yd0 / n
    y  = (6.0 * (s - nt)) * x0 + y0 - 2.0 * (1.0 - c) * xd0 / n + (4.0 * s - 3.0 * nt) * yd0 / n
    z  = z0 * c + zd0 * s / n

    xd = 3.0 * n * s * x0 + c * xd0 + 2.0 * s * yd0
    yd = 6.0 * n * (c - 1.0) * x0 - 2.0 * s * xd0 + (4.0 * c - 3.0) * yd0
    zd = -z0 * n * s + zd0 * c

    return CWState(x=x, y=y, z=z, xd=xd, yd=yd, zd=zd)


def _build_trajectory(
    state0: CWState,
    n: float,
    tof_s: float,
    n_points: int = _N_POINTS,
) -> list[TrajectoryPoint]:
    """Generate trajectory points by stepping the CW propagator."""
    if tof_s <= 0.0:
        return [TrajectoryPoint(0.0, state0.x, state0.y, state0.z,
                                math.sqrt(state0.x**2 + state0.y**2 + state0.z**2))]
    dt = tof_s / n_points
    points: list[TrajectoryPoint] = []
    s = state0
    for i in range(n_points + 1):
        t = i * dt
        rng = math.sqrt(s.x**2 + s.y**2 + s.z**2)
        points.append(TrajectoryPoint(t_s=t, x_km=s.x, y_km=s.y, z_km=s.z, range_km=rng))
        if i < n_points:
            s = _cw_propagate(state0, n, (i + 1) * dt)
    return points


def _initial_hill_state(
    red_tle: str,
    blue_tle: str,
    epoch: datetime,
) -> tuple[CWState, float, float, float]:
    """Compute the initial relative state in the Hill frame at *epoch*.

    Returns
    -------
    state : CWState
        Relative position (km) and velocity (km/s) in Hill frame.
    n : float
        Target mean motion (rad/s).
    initial_range_km : float
        Euclidean separation at epoch.
    ecc : float
        Target orbital eccentricity (for validity warning).
    """
    try:
        red_orbit  = TLEOrbit(red_tle)
        blue_orbit = TLEOrbit(blue_tle)
    except (ValueError, RuntimeError) as exc:
        raise RelativeGeometryError(f"TLE parse failed: {exc}") from exc

    sv_red  = red_orbit.propagate(epoch)
    sv_blue = blue_orbit.propagate(epoch)

    kep = state_to_keplerian(sv_blue)
    n   = float(np.sqrt(MU_EARTH / kep.a ** 3))
    ecc = kep.ecc

    if n < _N_MIN_RAD_S:
        raise RelativeGeometryError(
            f"Target mean motion ({n:.3e} rad/s) is below minimum threshold "
            f"— object may be on a hyperbolic or very deep orbit."
        )

    # ECI → Hill rotation matrix (using blue as reference).
    R_hill = _eci_to_hill_matrix(sv_blue.r, sv_blue.v)

    # Relative position in Hill frame.
    dr_eci = sv_red.r - sv_blue.r
    r_rel  = R_hill @ dr_eci          # shape (3,)

    # Relative velocity in Hill frame, accounting for frame rotation.
    # v_rel_hill = R * (v_red - v_blue) - ω × r_rel
    # where ω = [0, 0, n] in Hill frame → ω × r_rel = [-n·y, n·x, 0]
    dv_eci     = sv_red.v - sv_blue.v
    v_rel_rot  = R_hill @ dv_eci
    omega_cross = np.array([-n * r_rel[1], n * r_rel[0], 0.0])
    v_rel = v_rel_rot - omega_cross

    initial_range = float(np.linalg.norm(dr_eci))

    state = CWState(
        x=float(r_rel[0]),
        y=float(r_rel[1]),
        z=float(r_rel[2]),
        xd=float(v_rel[0]),
        yd=float(v_rel[1]),
        zd=float(v_rel[2]),
    )
    return state, n, initial_range, ecc


def _apply_dv(state: CWState, dv_radial: float, dv_prograde: float, dv_normal: float) -> CWState:
    """Apply a ΔV impulse (km/s) in the Hill frame to a CW state."""
    return CWState(
        x=state.x,
        y=state.y,
        z=state.z,
        xd=state.xd + dv_radial,
        yd=state.yd + dv_prograde,
        zd=state.zd + dv_normal,
    )


def _check_validity(
    initial_range_km: float,
    ecc: float,
    tof_hours: float,
) -> tuple[bool, list[str]]:
    """Assess whether the CW approximation is reliable for these inputs."""
    notes: list[str] = []
    valid = True

    if initial_range_km > _CW_RANGE_WARN_KM:
        valid = False
        notes.append(
            f"Initial separation {initial_range_km:.0f} km exceeds CW validity range "
            f"(~{_CW_RANGE_WARN_KM:.0f} km). Trajectory shape is indicative only."
        )
    if ecc > _ECC_WARN_THRESHOLD:
        valid = False
        notes.append(
            f"Target orbit eccentricity {ecc:.4f} > {_ECC_WARN_THRESHOLD}. "
            f"CW assumes circular reference orbit; errors grow with eccentricity."
        )
    if tof_hours > _TOF_WARN_HOURS:
        notes.append(
            f"Time of flight {tof_hours:.1f} h exceeds {_TOF_WARN_HOURS} h. "
            f"Secular drift terms may cause CW trajectory to diverge from truth."
        )
    if not notes:
        notes.append("CW approximation valid for this geometry.")

    return valid, notes


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_relative_geometry(
    red_tle: str,
    blue_tle: str,
    burn_epoch: datetime,
    dv_radial_km_s: float,
    dv_prograde_km_s: float,
    dv_normal_km_s: float,
    tof_s: float,
    method: str,
    red_name: str = "RED",
    blue_name: str = "BLUE",
    coast_s: float = 0.0,
    *,
    caller: str = "unknown",
) -> RelativeGeometry:
    """Compute relative geometry of an intercept manoeuvre in the Hill frame.

    Parameters
    ----------
    red_tle : str
        TLE string for the chaser (red) satellite.
    blue_tle : str
        TLE string for the target (blue) satellite.
    burn_epoch : datetime
        UTC epoch of the first burn.
    dv_radial_km_s : float
        Radial (R-bar) ΔV component in km/s.
    dv_prograde_km_s : float
        Prograde (V-bar) ΔV component in km/s.
    dv_normal_km_s : float
        Normal (H-bar) ΔV component in km/s.
    tof_s : float
        Post-burn time of flight in seconds.
    method : str
        Human-readable method label for the result record.
    red_name : str
        Display name of the chaser satellite (sanitised before logging).
    blue_name : str
        Display name of the target satellite (sanitised before logging).
    coast_s : float
        Optional pre-burn coast duration in seconds (default 0).
    caller : str
        Username or component name for audit logging.

    Returns
    -------
    RelativeGeometry
        Complete trajectory data and chart-ready series.

    Raises
    ------
    RelativeGeometryError
        If inputs are invalid or computation cannot proceed.
    """
    # ── Input sanitisation and validation ────────────────────────────────────
    red_name_safe  = _sanitise_name(red_name)
    blue_name_safe = _sanitise_name(blue_name)
    method_safe    = _sanitise_name(method)

    for val, label in [
        (dv_radial_km_s,   "dv_radial_km_s"),
        (dv_prograde_km_s, "dv_prograde_km_s"),
        (dv_normal_km_s,   "dv_normal_km_s"),
        (tof_s,            "tof_s"),
        (coast_s,          "coast_s"),
    ]:
        _validate_finite(val, label)

    dv_total = math.sqrt(dv_radial_km_s**2 + dv_prograde_km_s**2 + dv_normal_km_s**2)
    if dv_total > _DV_HARD_CAP_KM_S:
        raise RelativeGeometryError(
            f"Total ΔV {dv_total:.2f} km/s exceeds hard cap "
            f"{_DV_HARD_CAP_KM_S} km/s — check input units."
        )
    if tof_s < 0.0:
        raise RelativeGeometryError(f"tof_s must be non-negative, got {tof_s}")
    if coast_s < 0.0:
        raise RelativeGeometryError(f"coast_s must be non-negative, got {coast_s}")
    if not burn_epoch.tzinfo:
        raise RelativeGeometryError("burn_epoch must be timezone-aware (UTC)")

    if not red_tle.strip() or not blue_tle.strip():
        raise RelativeGeometryError("red_tle and blue_tle must not be empty")

    # ── Audit log ─────────────────────────────────────────────────────────────
    logger.info(
        "cw_geometry: caller=%r red=%r blue=%r method=%r "
        "dv_r=%.4f dv_p=%.4f dv_n=%.4f tof=%.1fs coast=%.1fs epoch=%s",
        caller, red_name_safe, blue_name_safe, method_safe,
        dv_radial_km_s, dv_prograde_km_s, dv_normal_km_s,
        tof_s, coast_s, burn_epoch.isoformat(),
    )

    # ── Compute initial relative state at burn epoch ──────────────────────────
    try:
        state0, n, initial_range, ecc = _initial_hill_state(red_tle, blue_tle, burn_epoch)
    except Exception as exc:
        logger.error(
            "cw_geometry: failed to compute initial state for %r/%r: %s",
            red_name_safe, blue_name_safe, exc,
        )
        raise RelativeGeometryError(f"SGP4 propagation failed: {exc}") from exc

    if initial_range > _RANGE_HARD_CAP_KM:
        logger.warning(
            "cw_geometry: initial separation %.0f km between %r and %r "
            "exceeds hard cap %d km — CW result will be unreliable",
            initial_range, red_name_safe, blue_name_safe, _RANGE_HARD_CAP_KM,
        )

    tof_hours = tof_s / 3600.0
    cw_valid, validity_notes = _check_validity(initial_range, ecc, tof_hours)

    if not cw_valid:
        for note in validity_notes:
            logger.warning("cw_geometry validity: %s", note)

    # ── Pre-burn coast ────────────────────────────────────────────────────────
    coast_points: list[TrajectoryPoint] = []
    state_at_burn = state0
    if coast_s > 0.0:
        coast_points = _build_trajectory(state0, n, coast_s)
        state_at_burn = _cw_propagate(state0, n, coast_s)
        logger.debug("cw_geometry: coast %.0fs, state at burn: x=%.2f y=%.2f z=%.2f km",
                     coast_s, state_at_burn.x, state_at_burn.y, state_at_burn.z)

    # ── Apply ΔV ──────────────────────────────────────────────────────────────
    burn_state = _apply_dv(state_at_burn, dv_radial_km_s, dv_prograde_km_s, dv_normal_km_s)

    # ── Post-burn propagation ─────────────────────────────────────────────────
    transfer_points = _build_trajectory(burn_state, n, tof_s)
    arrival_range   = transfer_points[-1].range_km if transfer_points else 0.0

    logger.info(
        "cw_geometry: arrival range=%.3f km for %r → %r (%s)",
        arrival_range, red_name_safe, blue_name_safe, method_safe,
    )
    if arrival_range > 10.0:
        logger.warning(
            "cw_geometry: large arrival range %.3f km for %r → %r — "
            "CW linearisation error or solution mismatch",
            arrival_range, red_name_safe, blue_name_safe,
        )

    # ── Chart-ready series ────────────────────────────────────────────────────
    def _vr(pts: list[TrajectoryPoint]) -> list[tuple[float, float]]:
        return [(round(p.y_km, 4), round(p.x_km, 4)) for p in pts]

    def _hr(pts: list[TrajectoryPoint]) -> list[tuple[float, float]]:
        return [(round(p.z_km, 4), round(p.x_km, 4)) for p in pts]

    def _rt(pts: list[TrajectoryPoint]) -> list[tuple[float, float]]:
        return [(round(p.t_s, 1), round(p.range_km, 4)) for p in pts]

    geom = RelativeGeometry(
        method=method_safe,
        red_name=red_name_safe,
        blue_name=blue_name_safe,
        n_rad_s=round(n, 8),
        initial_range_km=round(initial_range, 3),
        tof_hours=round(tof_hours, 4),
        dv_total_ms=round(dv_total * 1000.0, 2),
        burn_epoch=burn_epoch,
        cw_valid=cw_valid,
        validity_notes=validity_notes,
        coast_points=coast_points,
        transfer_points=transfer_points,
        burn_state=burn_state,
        arrival_range_km=round(arrival_range, 4),
        vr_coast=_vr(coast_points),
        vr_transfer=_vr(transfer_points),
        hr_coast=_hr(coast_points),
        hr_transfer=_hr(transfer_points),
        range_series=_rt(coast_points) + _rt(transfer_points),
    )

    return geom
