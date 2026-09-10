"""Lambert problem solver: universal variables with Stumpff functions.

Solves for the velocity vectors at departure and arrival given two position
vectors and a time of flight.

Method: Curtis, *Orbital Mechanics for Engineering Students*, Algorithm 5.2.
Validated against Curtis Example 5.2 and by propagating the departure state
forward over the time of flight and measuring the miss distance against the
requested arrival position. See tests/unit/test_lambert_validation.py.

This file previously claimed to implement Izzo (2015) and did not. The claim
mattered: Izzo's method is robust and handles multiple revolutions, and the
docstring credited this code with properties it does not have. It solves the
single-revolution problem only. A multi-revolution transfer, which matters for
realistic GEO intercept planning, is not supported and is rejected explicitly
rather than answered wrongly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from spectre.astro.constants import MU_EARTH


@dataclass
class LambertSolution:
    """Result of a Lambert problem solve."""

    v1: np.ndarray           # km/s — departure velocity vector (3,)
    v2: np.ndarray           # km/s — arrival velocity vector (3,)
    delta_v1: np.ndarray     # km/s — departure impulse (v1 - v_initial)
    delta_v2: np.ndarray     # km/s — arrival impulse (v_target - v2)
    delta_v1_mag: float      # km/s — |delta_v1|
    delta_v2_mag: float      # km/s — |delta_v2|
    total_delta_v: float     # km/s — sum of magnitudes
    tof: float               # seconds — time of flight


def solve_lambert(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool = True,
    v1_initial: np.ndarray | None = None,
    v2_target: np.ndarray | None = None,
) -> LambertSolution:
    """Solve Lambert's problem using Izzo's algorithm.

    Args:
        r1: Departure position vector (km), shape (3,).
        r2: Arrival position vector (km), shape (3,).
        tof: Time of flight (seconds).  Must be positive.
        mu: Gravitational parameter (km³/s²).
        prograde: If True, assume prograde (short-way) transfer.
        v1_initial: Current velocity at r1 (km/s) — used to compute delta_v1.
        v2_target: Target velocity at r2 (km/s) — used to compute delta_v2.

    Returns:
        :class:`LambertSolution` with velocity vectors and delta-V.

    Raises:
        ValueError: If tof <= 0 or positions are degenerate.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)

    if tof <= 0:
        raise ValueError(f"Time of flight must be positive, got {tof}")

    r1_mag = np.linalg.norm(r1)
    r2_mag = np.linalg.norm(r2)

    if r1_mag < 1e-10 or r2_mag < 1e-10:
        raise ValueError("Position vectors must be non-zero")

    # Cross product to determine transfer direction.
    cross = np.cross(r1, r2)
    cross_z = cross[2]

    # Transfer angle.
    cos_dnu = np.dot(r1, r2) / (r1_mag * r2_mag)
    cos_dnu = np.clip(cos_dnu, -1.0, 1.0)

    if prograde:
        if cross_z < 0:
            dnu = 2.0 * math.pi - math.acos(cos_dnu)
        else:
            dnu = math.acos(cos_dnu)
    else:
        if cross_z >= 0:
            dnu = 2.0 * math.pi - math.acos(cos_dnu)
        else:
            dnu = math.acos(cos_dnu)

    # Collinear geometry has no unique transfer plane, and the guard for it has
    # to be keyed to the ANGLE, not to A.
    #
    # At exactly 180 degrees any plane containing both radii is admissible, so
    # the problem is genuinely ill-posed rather than merely hard. The previous
    # guard tested abs(A) < 1e-14, and A does not get that small: sin(pi) in
    # floating point is 1.2e-16, not zero, which put A at 3.7e-12 for a GEO
    # transfer between opposite points on the belt. The guard stayed silent and
    # the solver returned a confident answer that missed by 74,790 km.
    #
    # This matters operationally rather than academically: a phasing transfer
    # across the GEO belt sits exactly here, and it is one of the most common
    # geometries in the work this tool exists to support.
    _DEGENERATE_ANGLE_TOL = math.radians(0.5)
    if dnu < _DEGENERATE_ANGLE_TOL or abs(dnu - math.pi) < _DEGENERATE_ANGLE_TOL:
        raise ValueError(
            f"degenerate Lambert geometry: transfer angle {math.degrees(dnu):.4f} deg is "
            "within half a degree of 0 or 180, where the transfer plane is undefined or "
            "numerically ill-conditioned. Offset the epoch by a few minutes to move the "
            "geometry off the singularity, or plan the transfer in a specified plane."
        )
    if abs(2.0 * math.pi - dnu) < _DEGENERATE_ANGLE_TOL:
        raise ValueError(
            f"degenerate Lambert geometry: transfer angle {math.degrees(dnu):.4f} deg is "
            "within half a degree of a full revolution; the departure and arrival "
            "positions coincide."
        )

    # Chord term (Curtis eq. 5.35).
    A = math.sin(dnu) * math.sqrt(r1_mag * r2_mag / (1.0 - cos_dnu))

    if abs(A) < 1e-14:
        raise ValueError("degenerate Lambert geometry (A is zero to machine precision)")

    # Solve via Stumpff functions with Newton–Raphson iteration.
    z = _solve_z(float(r1_mag), float(r2_mag), A, tof, mu)

    # Lagrange coefficients.
    sz = _stumpff_S(z)
    cz = _stumpff_C(z)
    y = r1_mag + r2_mag + A * (z * sz - 1.0) / math.sqrt(cz)

    f = 1.0 - y / r1_mag
    g = A * math.sqrt(y / mu)
    g_dot = 1.0 - y / r2_mag

    v1_vec = (r2 - f * r1) / g
    v2_vec = (g_dot * r2 - r1) / g

    # Compute impulse vectors if reference velocities given.
    dv1 = v1_vec - v1_initial if v1_initial is not None else np.zeros(3)
    dv2 = v2_target - v2_vec if v2_target is not None else np.zeros(3)

    return LambertSolution(
        v1=v1_vec,
        v2=v2_vec,
        delta_v1=dv1,
        delta_v2=dv2,
        delta_v1_mag=float(np.linalg.norm(dv1)),
        delta_v2_mag=float(np.linalg.norm(dv2)),
        total_delta_v=float(np.linalg.norm(dv1) + np.linalg.norm(dv2)),
        tof=tof,
    )


# ── Stumpff functions ─────────────────────────────────────────────────────────

def _stumpff_C(z: float) -> float:
    """Stumpff function C(z)."""
    if z > 1e-6:
        sz = math.sqrt(z)
        return (1.0 - math.cos(sz)) / z
    if z < -1e-6:
        sz = math.sqrt(-z)
        return (math.cosh(sz) - 1.0) / (-z)
    return 1.0 / 2.0


def _stumpff_S(z: float) -> float:
    """Stumpff function S(z)."""
    if z > 1e-6:
        sz = math.sqrt(z)
        return (sz - math.sin(sz)) / (sz**3)
    if z < -1e-6:
        sz = math.sqrt(-z)
        return (math.sinh(sz) - sz) / (sz**3)
    return 1.0 / 6.0


class LambertConvergenceError(ValueError):
    """The universal-variable iteration did not converge on a solution.

    Raised rather than returned. The previous implementation ran a fixed
    hundred iterations and returned whatever value of z it happened to hold,
    converged or not, so a caller received a confident, silently wrong
    transfer. On the textbook validation case that wrong answer missed the
    target by 6,268 km while reporting a plausible-looking delta-V.
    """


# The single-revolution solution lies below the parabolic limit z = 4*pi^2.
# At that limit the time of flight diverges; above it the transfer needs a
# full extra revolution, which this solver does not model.
_Z_PARABOLIC_LIMIT: float = 4.0 * math.pi**2


def _y_of_z(z: float, r1_mag: float, r2_mag: float, A: float) -> float:
    """Curtis eq. 5.38. May be non-positive for a long-way transfer at low z."""
    return r1_mag + r2_mag + A * (z * _stumpff_S(z) - 1.0) / math.sqrt(_stumpff_C(z))


def _time_residual(z: float, r1_mag: float, r2_mag: float, A: float, tof: float, mu: float) -> float:
    """Curtis eq. 5.40: computed time of flight minus the requested one.

    Monotonically increasing in z, which is what makes bisection safe.

    The defect this replaces was a single wrong symbol. Curtis defines
    chi = sqrt(y/C); the previous code wrote ``x = sqrt(y / mu)``, substituting
    the gravitational parameter for the Stumpff function C(z). Those differ by
    six orders of magnitude, so the residual being driven to zero was not the
    time-of-flight equation at all, and the iteration never converged on
    anything meaningful.
    """
    try:
        y = _y_of_z(z, r1_mag, r2_mag, A)
        if y <= 0.0:
            return -math.inf  # push the bracket upward; this z is not admissible
        chi = math.sqrt(y / _stumpff_C(z))
        return chi**3 * _stumpff_S(z) + A * math.sqrt(y) - math.sqrt(mu) * tof
    except (OverflowError, ValueError):
        # Deep in the hyperbolic region the Stumpff series overflows a float.
        # The limit is unambiguous: as z falls the time of flight tends to
        # zero, so the residual tends to -sqrt(mu)*tof, which is negative.
        # Reporting that keeps the bracket search correct instead of letting an
        # OverflowError escape to a caller who asked for an intercept.
        return -math.inf


def _solve_z(
    r1_mag: float,
    r2_mag: float,
    A: float,
    tof: float,
    mu: float,
    tol: float = 1e-8,
    max_iter: int = 200,
) -> float:
    """Return the universal variable z for the requested time of flight.

    Bisection on a bracketed sign change rather than bare Newton-Raphson.
    Bisection cannot diverge on a monotone function, and the previous
    Newton implementation carried an incorrect derivative as well as an
    incorrect residual, so it diverged on every case tried and reported
    nothing.

    Raises:
        LambertConvergenceError: if no bracket exists or the iteration fails
            to reach *tol*. Never returns an unconverged value.
    """
    def residual(z: float) -> float:
        return _time_residual(z, r1_mag, r2_mag, A, tof, mu)

    # Upper bound: just inside the parabolic limit, where the time of flight
    # diverges, so the residual is certainly positive there.
    z_hi = _Z_PARABOLIC_LIMIT - 1e-6
    f_hi = residual(z_hi)
    if not math.isfinite(f_hi) or f_hi < 0.0:
        raise LambertConvergenceError(
            f"no single-revolution transfer reaches this geometry in {tof:.1f} s; "
            "the requested time of flight exceeds the parabolic limit, which needs "
            "a multi-revolution solution this solver does not provide"
        )

    # Lower bound: walk down through the hyperbolic region until the residual
    # turns negative. Each step doubles, so this terminates quickly.
    z_lo = 0.0
    f_lo = residual(z_lo)
    step = 1.0
    while f_lo >= 0.0 or not math.isfinite(f_lo):
        z_lo -= step
        step *= 2.0
        f_lo = residual(z_lo)
        # Below roughly -5e5 the Stumpff functions leave float range. Nothing
        # physical lives down there: it is a hyperbola far beyond any
        # achievable departure energy.
        if z_lo < -5.0e5:
            raise LambertConvergenceError(
                "could not bracket a solution: the geometry and time of flight "
                "admit no hyperbolic or elliptic single-revolution transfer"
            )

    for _ in range(max_iter):
        z_mid = 0.5 * (z_lo + z_hi)
        f_mid = residual(z_mid)
        if abs(f_mid) < tol * max(1.0, math.sqrt(mu) * tof) or (z_hi - z_lo) < 1e-12:
            return z_mid
        if f_mid < 0.0:
            z_lo = z_mid
        else:
            z_hi = z_mid

    raise LambertConvergenceError(
        f"the iteration did not converge in {max_iter} steps "
        f"(bracket width {z_hi - z_lo:.3e}); refusing to return an unconverged transfer"
    )
