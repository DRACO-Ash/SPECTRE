"""Lambert arc direction must follow the satellite's own motion.

"Prograde" in Curtis Algorithm 5.2 means a positive z component of r1 x r2.
For a retrograde orbit (inclination above 90 degrees, so every sun-synchronous
orbit) that convention picks the arc that runs against the satellite's motion,
and the departure burn has to reverse it: about 15 km/s per burn in LEO
instead of a few hundred m/s (audit F-003). With the departure velocity known,
the solver takes the arc whose angular momentum agrees with the departure
orbit's.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.lambert import solve_lambert

_R = 7000.0
_V = math.sqrt(MU_EARTH / _R)
_N = _V / _R


def _circular(inc_deg: float, u_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Position and velocity on a circular orbit, node on +x, argument of latitude u."""
    i, u = math.radians(inc_deg), math.radians(u_deg)
    node = np.array([1.0, 0.0, 0.0])
    in_plane = np.array([0.0, math.cos(i), math.sin(i)])
    r = _R * (math.cos(u) * node + math.sin(u) * in_plane)
    v = _V * (-math.sin(u) * node + math.cos(u) * in_plane)
    return r, v


@pytest.mark.parametrize("inc_deg", [51.6, 98.0, 135.0])
def test_a_short_in_plane_hop_is_cheap_in_either_sense_of_orbit(inc_deg: float) -> None:
    tof = 1800.0
    r1, v1 = _circular(inc_deg, 0.0)
    # Target leads by 10 deg and keeps flying for the time of flight.
    r2, v2 = _circular(inc_deg, 10.0 + math.degrees(_N * tof))

    solution = solve_lambert(r1, r2, tof, v1_initial=v1, v2_target=v2)

    assert solution.delta_v1_mag < 1.0, f"{solution.delta_v1_mag:.2f} km/s to depart at i={inc_deg}"
    h_departure = np.cross(r1, v1)
    h_transfer = np.cross(r1, solution.v1)
    assert float(np.dot(h_departure, h_transfer)) > 0.0, "the transfer arc runs against the orbit"


def test_an_explicit_direction_is_still_honoured() -> None:
    """The +z convention stays available to a caller who asks for it."""
    tof = 1800.0
    r1, v1 = _circular(98.0, 0.0)
    r2, _ = _circular(98.0, 10.0 + math.degrees(_N * tof))
    forced = solve_lambert(r1, r2, tof, prograde=True, v1_initial=v1)
    assert float(np.cross(r1, forced.v1)[2]) > 0.0
