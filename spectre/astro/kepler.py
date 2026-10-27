"""Two-body propagation by universal variables.

Method: Curtis, *Orbital Mechanics for Engineering Students*, Algorithm 3.3
(universal anomaly by Newton iteration) and Algorithm 3.4 (Lagrange f and g
coefficients). Valid for elliptic, parabolic and hyperbolic arcs, and for
times of flight longer than one period.

Used where a manoeuvre plan must be checked against where the interceptor
actually goes once a burn is applied, rather than where a closed-form transfer
assumes it goes.
"""

from __future__ import annotations

import math

import numpy as np

from spectre.astro.constants import MU_EARTH
from spectre.astro.lambert import _stumpff_C, _stumpff_S

_MAX_ITERATIONS = 100
_CHI_TOLERANCE = 1e-10
# Below this reciprocal semi-major axis (1/km) the orbit is treated as
# parabolic for the starting guess only.
_PARABOLIC_ALPHA = 1e-12


class KeplerConvergenceError(ValueError):
    """The universal-anomaly iteration did not converge."""


def _universal_anomaly(r0: float, vr0: float, alpha: float, dt: float, mu: float) -> float:
    """Solve the universal Kepler equation for chi (Curtis Algorithm 3.3)."""
    sqrt_mu = math.sqrt(mu)
    chi = sqrt_mu * abs(alpha) * dt if abs(alpha) > _PARABOLIC_ALPHA else sqrt_mu * dt / r0
    k = r0 * vr0 / sqrt_mu
    for _ in range(_MAX_ITERATIONS):
        z = alpha * chi * chi
        c, s = _stumpff_C(z), _stumpff_S(z)
        f = k * chi * chi * c + (1.0 - alpha * r0) * chi ** 3 * s + r0 * chi - sqrt_mu * dt
        df = k * chi * (1.0 - z * s) + (1.0 - alpha * r0) * chi * chi * c + r0
        step = f / df
        chi -= step
        if abs(step) < _CHI_TOLERANCE:
            return chi
    raise KeplerConvergenceError(f"universal anomaly did not converge for dt={dt:.1f} s")


def propagate_two_body(
    r0: np.ndarray, v0: np.ndarray, dt: float, mu: float = MU_EARTH,
) -> tuple[np.ndarray, np.ndarray]:
    """Return position and velocity *dt* seconds after (r0, v0) under two-body motion."""
    r0_mag = float(np.linalg.norm(r0))
    v0_mag = float(np.linalg.norm(v0))
    vr0 = float(np.dot(r0, v0)) / r0_mag
    alpha = 2.0 / r0_mag - v0_mag * v0_mag / mu

    chi = _universal_anomaly(r0_mag, vr0, alpha, dt, mu)
    z = alpha * chi * chi
    c, s = _stumpff_C(z), _stumpff_S(z)

    f = 1.0 - chi * chi / r0_mag * c
    g = dt - chi ** 3 * s / math.sqrt(mu)
    r = f * r0 + g * v0
    r_mag = float(np.linalg.norm(r))
    f_dot = math.sqrt(mu) / (r_mag * r0_mag) * (z * chi * s - chi)
    g_dot = 1.0 - chi * chi / r_mag * c
    v = f_dot * r0 + g_dot * v0
    return r, v
