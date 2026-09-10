"""Numerical validation of the Lambert solver against published references.

Why this file exists
--------------------
The solver was wrong. Every intercept delta-V, every transfer cost and every
entry in the threat sweep that went through it was wrong, and nothing noticed
for the life of the project, because the tests that existed asserted only that
the answer had the right *shape*: a velocity magnitude within 15 per cent of
circular, a delta-V greater than zero. A transfer that misses its target by
6,268 km satisfies both.

Two defects, each independently sufficient to produce a confident wrong answer:

1. The time-of-flight residual substituted the gravitational parameter for the
   Stumpff function C(z). Curtis defines chi = sqrt(y/C); the code computed
   sqrt(y/mu). Those differ by six orders of magnitude, so the Newton iteration
   was not solving the time-of-flight equation, never converged, and the
   routine returned its unconverged value without complaint.
2. The degeneracy guard was keyed to the chord term A rather than to the
   transfer angle. At exactly 180 degrees the transfer plane is undefined, but
   sin(pi) in floating point is 1.2e-16 rather than zero, so A stayed at
   3.7e-12 and the guard never fired. A phasing transfer between opposite
   points on the GEO belt sits exactly there.

The checks below are the ones that would have caught it: a published answer to
compare against, and a round trip that propagates the computed departure state
forward and measures where it actually arrives. The round trip is the stronger
of the two, because it needs no reference data and applies to any geometry.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.lambert import (
    LambertConvergenceError,
    _stumpff_C,
    _stumpff_S,
    solve_lambert,
)


def _propagate(r0: np.ndarray, v0: np.ndarray, dt: float, mu: float = MU_EARTH) -> np.ndarray:
    """Universal-variable Kepler propagation, independent of the solver.

    Deliberately a separate implementation. Verifying the solver with machinery
    the solver shares would only prove the two agree, which is what the
    original defect already did.
    """
    r0 = np.asarray(r0, dtype=float)
    v0 = np.asarray(v0, dtype=float)
    r0_mag = float(np.linalg.norm(r0))
    vr0 = float(np.dot(r0, v0) / r0_mag)
    alpha = 2.0 / r0_mag - float(np.linalg.norm(v0)) ** 2 / mu

    chi = math.sqrt(mu) * abs(alpha) * dt
    for _ in range(300):
        z = alpha * chi * chi
        c, s = _stumpff_C(z), _stumpff_S(z)
        f = (
            r0_mag * vr0 / math.sqrt(mu) * chi * chi * c
            + (1.0 - alpha * r0_mag) * chi**3 * s
            + r0_mag * chi
            - math.sqrt(mu) * dt
        )
        df = (
            r0_mag * vr0 / math.sqrt(mu) * chi * (1.0 - alpha * chi * chi * s)
            + (1.0 - alpha * r0_mag) * chi * chi * c
            + r0_mag
        )
        step = f / df
        chi -= step
        if abs(step) < 1e-11:
            break
    else:  # pragma: no cover - the reference propagator converges on these cases
        pytest.fail("the reference propagator did not converge; the check is void")

    z = alpha * chi * chi
    c, s = _stumpff_C(z), _stumpff_S(z)
    lagrange_f = 1.0 - chi * chi / r0_mag * c
    lagrange_g = dt - chi**3 / math.sqrt(mu) * s
    return lagrange_f * r0 + lagrange_g * v0


class TestPublishedReference:
    """Curtis, Orbital Mechanics for Engineering Students, Example 5.2."""

    R1 = np.array([5000.0, 10000.0, 2100.0])
    R2 = np.array([-14600.0, 2500.0, 7000.0])
    TOF = 3600.0
    V1_PUBLISHED = np.array([-5.9925, 1.9254, 3.2456])
    V2_PUBLISHED = np.array([-3.3125, -4.1966, -0.38529])

    def test_departure_velocity_matches_the_published_answer(self) -> None:
        solution = solve_lambert(self.R1, self.R2, self.TOF, prograde=True)
        error_m_s = float(np.linalg.norm(solution.v1 - self.V1_PUBLISHED)) * 1000.0
        assert error_m_s < 1.0, (
            f"departure velocity is {error_m_s:.1f} m/s from the published answer. "
            "Before the fix this was 1,970 m/s."
        )

    def test_arrival_velocity_matches_the_published_answer(self) -> None:
        solution = solve_lambert(self.R1, self.R2, self.TOF, prograde=True)
        error_m_s = float(np.linalg.norm(solution.v2 - self.V2_PUBLISHED)) * 1000.0
        assert error_m_s < 1.0, (
            f"arrival velocity is {error_m_s:.1f} m/s from the published answer. "
            "Before the fix this was 2,077 m/s."
        )


class TestRoundTripResidual:
    """Fly the answer and see where it lands.

    This is the check that needs no reference data, so it is the one to apply
    to any new geometry. A solver can only pass it by being right.
    """

    # Geometries that matter operationally, not just numerically.
    CASES = {
        "curtis-5.2": (np.array([5000.0, 10000.0, 2100.0]),
                       np.array([-14600.0, 2500.0, 7000.0]), 3600.0),
        "geo-quarter-belt": (np.array([42164.0, 0.0, 0.0]),
                             np.array([0.0, 42164.0, 0.0]), 21600.0),
        "geo-170-degrees": (np.array([42164.0, 0.0, 0.0]),
                            np.array([-41523.5, 7321.6, 0.0]), 21600.0),
        "leo-short-hop": (np.array([7000.0, 0.0, 0.0]),
                          np.array([0.0, 7000.0, 0.0]), 600.0),
        "polar-inclined": (np.array([7000.0, 0.0, 0.0]),
                           np.array([0.0, 0.0, 7000.0]), 1500.0),
        "polar-descending": (np.array([7000.0, 0.0, 0.0]),
                             np.array([0.0, 0.0, -7000.0]), 1500.0),
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_the_transfer_actually_arrives(self, name: str) -> None:
        r1, r2, tof = self.CASES[name]
        solution = solve_lambert(r1, r2, tof)
        arrived = _propagate(r1, solution.v1, tof)
        miss_km = float(np.linalg.norm(arrived - r2))
        assert miss_km < 1.0, (
            f"{name}: the computed transfer misses the target by {miss_km:,.1f} km. "
            "A transfer that does not arrive is not a transfer."
        )

    def test_the_check_would_catch_a_wrong_answer(self) -> None:
        """The residual must be sensitive, or passing it means nothing.

        Perturb the departure velocity by 10 m/s and confirm the miss distance
        becomes large. A check that tolerates a wrong answer is not a check.
        """
        r1, r2, tof = self.CASES["curtis-5.2"]
        solution = solve_lambert(r1, r2, tof)
        nudged = solution.v1 + np.array([0.01, 0.0, 0.0])  # 10 m/s
        miss_km = float(np.linalg.norm(_propagate(r1, nudged, tof) - r2))
        assert miss_km > 10.0, (
            f"a 10 m/s error moved the arrival point by only {miss_km:.3f} km, "
            "so this residual is too insensitive to prove anything"
        )


class TestDegenerateGeometryIsRefused:
    """Collinear radii have no unique transfer plane. Say so, do not guess."""

    def test_exactly_180_degrees_is_refused(self) -> None:
        """The GEO belt phasing case that returned a 74,790 km miss."""
        with pytest.raises(ValueError, match="degenerate Lambert geometry"):
            solve_lambert(np.array([42164.0, 0.0, 0.0]),
                          np.array([-42164.0, 0.0, 0.0]), 21600.0)

    def test_near_180_degrees_is_refused(self) -> None:
        angle = math.radians(179.8)
        with pytest.raises(ValueError, match="degenerate Lambert geometry"):
            solve_lambert(
                np.array([42164.0, 0.0, 0.0]),
                np.array([42164.0 * math.cos(angle), 42164.0 * math.sin(angle), 0.0]),
                21600.0,
            )

    def test_near_zero_degrees_is_refused(self) -> None:
        angle = math.radians(0.2)
        with pytest.raises(ValueError, match="degenerate Lambert geometry"):
            solve_lambert(
                np.array([7000.0, 0.0, 0.0]),
                np.array([7000.0 * math.cos(angle), 7000.0 * math.sin(angle), 0.0]),
                60.0,
            )

    def test_a_geometry_just_outside_the_guard_still_solves(self) -> None:
        """The guard must not swallow the workable cases next to it."""
        angle = math.radians(178.0)
        solution = solve_lambert(
            np.array([42164.0, 0.0, 0.0]),
            np.array([42164.0 * math.cos(angle), 42164.0 * math.sin(angle), 0.0]),
            21600.0,
        )
        assert np.isfinite(solution.v1).all()


class TestNonConvergenceIsRaisedNotReturned:
    """An unconverged answer must never leave the function.

    The original implementation ran a fixed hundred iterations and returned
    whatever it held. That is how a 6,268 km miss reached the threat sweep
    wearing a plausible delta-V.
    """

    def test_an_impossible_time_of_flight_raises(self) -> None:
        with pytest.raises((LambertConvergenceError, ValueError)):
            # A quarter of the GEO belt in ten seconds.
            solve_lambert(np.array([42164.0, 0.0, 0.0]),
                          np.array([0.0, 42164.0, 0.0]), 10.0)

    def test_the_error_type_is_specific_enough_to_handle(self) -> None:
        assert issubclass(LambertConvergenceError, ValueError)
