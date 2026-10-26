"""Monte Carlo drag strength from B*.

Audit F-031. The B* to ballistic-coefficient conversion used an unsourced
constant built on the Earth radius in metres, giving m/(Cd A) = 31.9 kg/m^2
for B* = 1e-4 where the SGP4 relation gives 784.8: drag about 24.6 times too
strong, which dominated the 48 h semi-major axis spread below about 450 km.

Independent references: SGP4 defines B* = rho0 Cd A / (2 m) with
rho0 = 0.15696615 kg/m^2/ER (Vallado, Fundamentals of Astrodynamics and
Applications, SGP4 drag term), so Cd A / m = 12.741621 B*; and for a circular
orbit da/dt = -rho (Cd A / m) sqrt(mu a).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.monte_carlo import (
    _atmo_density_kg_m3,
    _ballistic_coefficient_kg_m2,
    _j2_drag_ode,
    _state_to_keplerian,
)


def test_an_iss_like_bstar_gives_an_iss_like_area_to_mass() -> None:
    cda_over_m = 1.0 / _ballistic_coefficient_kg_m2(3e-4)
    assert 0.002 < cda_over_m < 0.01
    assert cda_over_m == pytest.approx(12.741621 * 3e-4, rel=1e-9)


def test_a_48_hour_decay_at_450_km_matches_the_density_estimate() -> None:
    # 450 km sits inside one band of the density table. Its band edges are
    # discontinuous (2.7x at 400 km), which is recorded separately.
    a0 = R_EARTH + 450.0
    # Circular under J2 on the equator: J2 adds 3/2 J2 (R/r)^2 to the central
    # pull, and starting at the two-body speed instead leaves the orbit about
    # 17 km low at perigee, where the density is a fifth higher.
    v0 = math.sqrt(MU_EARTH / a0 * (1.0 + 1.5 * J2_EARTH * (R_EARTH / a0) ** 2))
    state0 = np.array([a0, 0.0, 0.0, 0.0, v0, 0.0])
    bstar = 3e-4
    bc = _ballistic_coefficient_kg_m2(bstar)
    span = 48 * 3600.0

    def final_sma(ballistic: float) -> float:
        out = solve_ivp(_j2_drag_ode, (0.0, span), state0, rtol=1e-10, atol=1e-10, args=(ballistic,))
        return _state_to_keplerian(out.y[:3, -1], out.y[3:, -1])[0]

    # The drag-free run cancels the J2 short-period terms in the osculating a.
    decay_m = (final_sma(bc) - final_sma(0.0)) * 1000.0
    expected_m = -_atmo_density_kg_m3(450.0) / bc * math.sqrt(MU_EARTH * 1e9 * a0 * 1e3) * span
    assert decay_m == pytest.approx(expected_m, rel=0.20)
