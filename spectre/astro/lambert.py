"""Lambert problem solver: universal variables with Stumpff functions.

Solves for the velocity vectors at departure and arrival given two position
vectors and a time of flight.

Method: Curtis, *Orbital Mechanics for Engineering Students*, Algorithm 5.2.
Validated against Curtis Example 5.2 and by propagating the departure state
forward over the time of flight and measuring the miss distance against the
requested arrival position. See tests/unit/test_lambert_validation.py.

This file previously claimed to implement Izzo (2015) and did not; it is the
universal-variable method throughout.

Multiple revolutions. :func:`solve_lambert` returns the zero-revolution arc,
which exists for any time of flight but grows very expensive once the flight
is longer than about one orbit: a 30 deg hop along GEO in 24 h costs 7.8 km/s
over its two burns on that arc, against 0.21 km/s going once round. The universal-variable time-of-flight equation also
holds above z = 4 pi^2, where each band (2 pi N)^2 < z < (2 pi (N + 1))^2 is a
transfer making N complete revolutions, with a minimum time of flight and two
branches either side of it. :func:`solve_lambert_all` returns every such
solution, and :func:`cheapest_lambert` the one costing least. Branches are
bracketed on a fixed grid of z, so a branch pair whose minimum time of flight
only just reaches the requested one can fall between grid points and be
missed; the other solutions are unaffected.
"""

from __future__ import annotations

import contextlib
import itertools
import math
from dataclasses import dataclass
from typing import NamedTuple

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
    revolutions: int = 0     # complete revolutions before arrival


def solve_lambert(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool | None = None,
    v1_initial: np.ndarray | None = None,
    v2_target: np.ndarray | None = None,
) -> LambertSolution:
    """Solve the single-revolution Lambert problem (Curtis Algorithm 5.2).

    Args:
        r1: Departure position vector (km), shape (3,).
        r2: Arrival position vector (km), shape (3,).
        tof: Time of flight (seconds).  Must be positive.
        mu: Gravitational parameter (km³/s²).
        prograde: Transfer sense. ``True`` takes the arc whose angular momentum
            has a positive z component (Curtis's "prograde"), ``False`` the
            opposite. ``None`` (default) follows the departure orbit: with
            *v1_initial* given, the arc continues the satellite's own direction
            of motion; without it, ``True`` is assumed. Prograde is not the
            same as short-way: which arc is shorter depends on the geometry.
        v1_initial: Current velocity at r1 (km/s) — used to compute delta_v1.
        v2_target: Target velocity at r2 (km/s) — used to compute delta_v2.

    Returns:
        :class:`LambertSolution` with velocity vectors and delta-V.

    Raises:
        ValueError: If tof <= 0 or positions are degenerate.
    """
    problem = _prepare(r1, r2, tof, prograde, v1_initial)
    z = _solve_z(problem.geom, tof, mu)
    return _solution(problem, z, mu, (v1_initial, v2_target), 0)


# PLR0913, PLR0917: mirrors solve_lambert's signature.
def solve_lambert_all(  # noqa: PLR0913, PLR0917
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool | None = None,
    v1_initial: np.ndarray | None = None,
    v2_target: np.ndarray | None = None,
) -> list[LambertSolution]:
    """Every transfer reaching r2 in *tof*: zero revolutions, then one, two and so on.

    Arguments as :func:`solve_lambert`. Each revolution count above zero
    contributes up to two solutions, the branches either side of that count's
    minimum time of flight. The search stops at the first count whose minimum
    time of flight exceeds *tof*, since more revolutions only take longer.

    Raises:
        ValueError: if the geometry is degenerate (as :func:`solve_lambert`).
        LambertConvergenceError: if no transfer of any revolution count exists.
    """
    problem = _prepare(r1, r2, tof, prograde, v1_initial)
    refs = (v1_initial, v2_target)
    found: list[LambertSolution] = []
    with contextlib.suppress(LambertConvergenceError):
        found.append(_solution(problem, _solve_z(problem.geom, tof, mu), mu, refs, 0))
    for revolutions in range(1, _MAX_REVOLUTIONS + 1):
        roots = _multi_revolution_z(problem.geom, tof, mu, revolutions)
        if roots is None:
            break
        found.extend(_solution(problem, z, mu, refs, revolutions) for z in roots)
    if not found:
        raise LambertConvergenceError(f"no transfer of any revolution count reaches this geometry in {tof:.1f} s")
    return found


# PLR0913, PLR0917: mirrors solve_lambert's signature.
def cheapest_lambert(  # noqa: PLR0913, PLR0917
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool | None = None,
    v1_initial: np.ndarray | None = None,
    v2_target: np.ndarray | None = None,
) -> LambertSolution:
    """The :func:`solve_lambert_all` solution with the least total delta-V."""
    return min(
        solve_lambert_all(r1, r2, tof, mu, prograde, v1_initial, v2_target),
        key=lambda s: s.total_delta_v,
    )


class _Problem(NamedTuple):
    """One Lambert problem after the geometry checks."""

    r1: np.ndarray
    r2: np.ndarray
    geom: _Geometry
    tof: float


def _prepare(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    prograde: bool | None,
    v1_initial: np.ndarray | None,
) -> _Problem:
    """Validate the inputs and fix the transfer angle and chord term."""
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

    # Transfer angle.
    cos_dnu = np.dot(r1, r2) / (r1_mag * r2_mag)
    cos_dnu = np.clip(cos_dnu, -1.0, 1.0)

    # acos returns the principal value in [0, pi], so the sense of r1 x r2
    # decides whether that is the transfer angle or its reflex. The prograde and
    # retrograde cases are mirror images of one another rather than two separate
    # rules: the long way round is taken whenever the requested direction
    # disagrees with the sign of the orbit normal.
    long_way = _takes_long_way(r1, cross, prograde, v1_initial)
    dnu = 2.0 * math.pi - math.acos(cos_dnu) if long_way else math.acos(cos_dnu)

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
    if dnu < _DEGENERATE_ANGLE_TOL_RAD or abs(dnu - math.pi) < _DEGENERATE_ANGLE_TOL_RAD:
        raise ValueError(
            f"degenerate Lambert geometry: transfer angle {math.degrees(dnu):.4f} deg is "
            "within half a degree of 0 or 180, where the transfer plane is undefined or "
            "numerically ill-conditioned. Offset the epoch by a few minutes to move the "
            "geometry off the singularity, or plan the transfer in a specified plane."
        )
    if abs(2.0 * math.pi - dnu) < _DEGENERATE_ANGLE_TOL_RAD:
        raise ValueError(
            f"degenerate Lambert geometry: transfer angle {math.degrees(dnu):.4f} deg is "
            "within half a degree of a full revolution; the departure and arrival "
            "positions coincide."
        )

    # Chord term (Curtis eq. 5.35).
    A = math.sin(dnu) * math.sqrt(r1_mag * r2_mag / (1.0 - cos_dnu))

    if abs(A) < 1e-14:
        raise ValueError("degenerate Lambert geometry (A is zero to machine precision)")

    return _Problem(r1, r2, _Geometry(float(r1_mag), float(r2_mag), A), tof)



def _solution(
    problem: _Problem,
    z: float,
    mu: float,
    refs: tuple[np.ndarray | None, np.ndarray | None],
    revolutions: int,
) -> LambertSolution:
    """Build the velocities and impulses for a converged z."""
    r1, r2, geom, tof = problem
    r1_mag, r2_mag, chord = geom
    v1_initial, v2_target = refs

    # Lagrange coefficients.
    sz = _stumpff_S(z)
    cz = _stumpff_C(z)
    y = r1_mag + r2_mag + chord * (z * sz - 1.0) / math.sqrt(cz)

    f = 1.0 - y / r1_mag
    g = chord * math.sqrt(y / mu)
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
        revolutions=revolutions,
    )


def _takes_long_way(
    r1: np.ndarray,
    cross: np.ndarray,
    prograde: bool | None,
    v1_initial: np.ndarray | None,
) -> bool:
    """Return ``True`` when the transfer takes the reflex (2*pi - angle) arc.

    *cross* is r1 x r2. With *prograde* ``None`` and a departure velocity
    known, the arc follows the satellite's own sense of motion. Keyed to +z
    alone, as it was, every retrograde orbit (inclination above 90 deg, so
    every sun-synchronous orbit) took the arc running against its motion and
    the departure burn had to reverse it: about 15 km/s in LEO instead of a
    few hundred m/s (audit F-003). An explicit ``True`` or ``False`` keeps
    Curtis's convention: positive or negative z component of r1 x r2.
    """
    if prograde is None and v1_initial is not None:
        h_departure = np.cross(r1, np.asarray(v1_initial, dtype=float))
        return float(np.dot(cross, h_departure)) < 0.0
    heading_plus_z = True if prograde is None else prograde
    return bool(cross[2] < 0) if heading_plus_z else bool(cross[2] >= 0)


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


# Transfer angles within this tolerance of 0 or pi have no unique transfer
# plane; see the guard in solve_lambert for why it is keyed to the angle.
_DEGENERATE_ANGLE_TOL_RAD: float = math.radians(0.5)

# Below this the Stumpff series leaves float range. Nothing physical lives
# there: it is a hyperbola far beyond any achievable departure energy.
_Z_HYPERBOLIC_FLOOR: float = -5.0e5

# Bracket width at which further bisection buys nothing.
_Z_BRACKET_EPSILON: float = 1e-12

# Multi-revolution search: grid points per revolution band, bisection steps
# per root, and a ceiling on the revolution count (100 GEO days).
_MULTI_REV_GRID: int = 256
_BISECT_STEPS: int = 200
_MAX_REVOLUTIONS: int = 100
_EDGE_HALVINGS: int = 60

# The zero-revolution solution lies below z = 4*pi^2, where its time of flight
# diverges; above it each band of z is one more complete revolution, solved by
# _multi_revolution_z.
_Z_SINGLE_REV_LIMIT: float = 4.0 * math.pi**2


class _Geometry(NamedTuple):
    """The fixed geometry of one Lambert problem: two radii and the chord term."""

    r1_mag: float
    r2_mag: float
    chord: float  # Curtis writes this A (eq. 5.35)


def _y_of_z(z: float, geom: _Geometry) -> float:
    """Curtis eq. 5.38. May be non-positive for a long-way transfer at low z."""
    return (
        geom.r1_mag + geom.r2_mag
        + geom.chord * (z * _stumpff_S(z) - 1.0) / math.sqrt(_stumpff_C(z))
    )


def _time_residual(z: float, geom: _Geometry, tof: float, mu: float) -> float:
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
        y = _y_of_z(z, geom)
        if y <= 0.0:
            return -math.inf  # push the bracket upward; this z is not admissible
        chi = math.sqrt(y / _stumpff_C(z))
        return chi**3 * _stumpff_S(z) + geom.chord * math.sqrt(y) - math.sqrt(mu) * tof
    except (OverflowError, ValueError):
        # Deep in the hyperbolic region the Stumpff series overflows a float.
        # The limit is unambiguous: as z falls the time of flight tends to
        # zero, so the residual tends to -sqrt(mu)*tof, which is negative.
        # Reporting that keeps the bracket search correct instead of letting an
        # OverflowError escape to a caller who asked for an intercept.
        return -math.inf


def _solve_z(
    geom: _Geometry,
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
        return _time_residual(z, geom, tof, mu)

    # Upper bound: just inside z = 4 pi^2, the end of the single-revolution branch, where the time of flight
    # diverges, so the residual is certainly positive there.
    z_hi = _Z_SINGLE_REV_LIMIT - 1e-6
    f_hi = residual(z_hi)
    if not math.isfinite(f_hi) or f_hi < 0.0:
        raise LambertConvergenceError(
            f"no single-revolution transfer reaches this geometry in {tof:.1f} s; "
            "use solve_lambert_all for transfers making complete revolutions"
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
        if z_lo < _Z_HYPERBOLIC_FLOOR:
            raise LambertConvergenceError(
                "could not bracket a solution: the geometry and time of flight "
                "admit no hyperbolic or elliptic single-revolution transfer"
            )

    for _ in range(max_iter):
        z_mid = 0.5 * (z_lo + z_hi)
        f_mid = residual(z_mid)
        if abs(f_mid) < tol * max(1.0, math.sqrt(mu) * tof) or (z_hi - z_lo) < _Z_BRACKET_EPSILON:
            return z_mid
        if f_mid < 0.0:
            z_lo = z_mid
        else:
            z_hi = z_mid

    raise LambertConvergenceError(
        f"the iteration did not converge in {max_iter} steps "
        f"(bracket width {z_hi - z_lo:.3e}); refusing to return an unconverged transfer"
    )


def _multi_revolution_z(geom: _Geometry, tof: float, mu: float, revolutions: int) -> list[float] | None:
    """Roots of the time-of-flight equation for *revolutions* complete revolutions.

    Within the band (2 pi N)^2 < z < (2 pi (N + 1))^2 the time of flight falls
    from infinity to a minimum and rises to infinity again, so there are two
    roots when the requested time is above that minimum and none below it.
    Each is bracketed on a fixed grid and then bisected. A near-circular drift
    whose transfer angle is close to 0 or 360 deg puts a root nearer the band
    edge than the first grid point, so when an end of the grid is already
    below the requested time the bracket is extended towards that edge.
    Returns None when no grid point reaches the requested time, which ends
    the caller's search.
    """
    lo = (2.0 * math.pi * revolutions) ** 2
    hi = (2.0 * math.pi * (revolutions + 1)) ** 2
    grid = [lo + (hi - lo) * k / _MULTI_REV_GRID for k in range(1, _MULTI_REV_GRID)]
    points = [(z, _time_residual(z, geom, tof, mu)) for z in grid]
    points = [(z, f) for z, f in points if math.isfinite(f)]
    if not any(f <= 0.0 for _, f in points):
        return None
    for edge, end in ((lo, 0), (hi, -1)):
        z_in, f_in = points[end]
        if f_in < 0.0:
            outer = _towards_edge(geom, tof, mu, z_in, edge)
            if outer is not None:
                points.insert(0 if end == 0 else len(points), outer)
    return [
        _bisect(geom, tof, mu, (z_a, f_a < 0.0), z_b)
        for (z_a, f_a), (z_b, f_b) in itertools.pairwise(points)
        if (f_a < 0.0) != (f_b < 0.0)
    ]


def _towards_edge(geom: _Geometry, tof: float, mu: float, z_in: float, edge: float) -> tuple[float, float] | None:
    """A point between *z_in* and the band *edge* where the residual is positive."""
    gap = edge - z_in
    for _ in range(_EDGE_HALVINGS):
        gap *= 0.5
        f = _time_residual(edge - gap, geom, tof, mu)
        if math.isfinite(f) and f > 0.0:
            return edge - gap, f
    return None


def _bisect(geom: _Geometry, tof: float, mu: float, start: tuple[float, bool], z_b: float) -> float:
    """Bisect the residual between start[0] (negative if start[1]) and z_b."""
    z_a, a_negative = start
    for _ in range(_BISECT_STEPS):
        z_mid = 0.5 * (z_a + z_b)
        if (_time_residual(z_mid, geom, tof, mu) < 0.0) == a_negative:
            z_a = z_mid
        else:
            z_b = z_mid
        if z_b - z_a < _Z_BRACKET_EPSILON * max(1.0, z_a):
            break
    return 0.5 * (z_a + z_b)
