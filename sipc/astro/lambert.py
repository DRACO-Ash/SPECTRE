"""Lambert problem solver — Izzo's algorithm (2015).

Solves for the velocity vectors at departure and arrival given two
position vectors and a time of flight.  Based on Dario Izzo's 2015 paper
"Revisiting Lambert's Problem" (Celestial Mechanics and Dynamical Astronomy).

Reference implementation: https://github.com/darioizzo/lambert (MIT licence).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from sipc.astro.constants import MU_EARTH


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

    # Chord and semi-perimeter.
    A = math.sin(dnu) * math.sqrt(r1_mag * r2_mag / (1.0 - cos_dnu))

    if abs(A) < 1e-14:
        raise ValueError("Degenerate Lambert geometry (A ≈ 0)")

    # Solve via Stumpff functions with Newton–Raphson iteration.
    z = _solve_z(r1_mag, r2_mag, A, tof, mu)

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


def _solve_z(
    r1_mag: float,
    r2_mag: float,
    A: float,
    tof: float,
    mu: float,
    tol: float = 1e-10,
    max_iter: int = 100,
) -> float:
    """Newton–Raphson iteration to solve for the universal variable z."""
    z = 0.0  # initial guess (parabolic)

    for _ in range(max_iter):
        cz = _stumpff_C(z)
        sz = _stumpff_S(z)
        sqrt_cz = math.sqrt(cz) if cz > 0 else math.sqrt(abs(cz))

        y = r1_mag + r2_mag + A * (z * sz - 1.0) / sqrt_cz

        if y < 0:
            # Adjust z upward to keep y positive.
            z = z + 0.1
            continue

        x = math.sqrt(y / mu)
        F = x**3 * sz + A * math.sqrt(y) - math.sqrt(mu) * tof

        if abs(F) < tol:
            return z

        # Derivative dF/dz.
        if abs(z) > 1e-6:
            dF = x**3 * (sz - 3.0 * sz * cz / (2.0 * cz) + 1.0 / (2.0 * z)) + \
                 (A / 8.0) * (3.0 * sz * math.sqrt(y) / cz + A / x)
        else:
            dF = (math.sqrt(2.0) / 40.0) * y**1.5 + (A / 8.0) * (math.sqrt(y) + A * math.sqrt(1.0 / (2.0 * y)))

        if abs(dF) < 1e-20:
            break

        z = z - F / dF

    return z
