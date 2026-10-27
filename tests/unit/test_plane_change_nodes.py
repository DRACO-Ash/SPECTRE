"""A pure plane change is priced at the nodes, where it can be flown.

Audit F-074. For an eccentric orbit plane_change took the circular speed at
the semi-major axis as "the speed at the node", offered "apogee" without
checking apogee lies on the line of nodes, and reported "apogee" for a
circular orbit, which has none. A plane change rotates the velocity about the
radius, so it costs 2 v_t sin(di / 2) with v_t = h / r the transverse speed
at the node (Curtis eq. 6.20), and the nodes sit at true anomaly -omega and
180 deg - omega.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.tactical import plane_change


def test_an_eccentric_orbit_is_priced_at_its_slower_node() -> None:
    a, e, argp, di = 10_000.0, 0.3, 30.0, 5.0
    p = a * (1 - e**2)
    h = math.sqrt(MU_EARTH * p)
    costs = {}
    for name, nu in (("ascending node", -argp), ("descending node", 180.0 - argp)):
        r = p / (1 + e * math.cos(math.radians(nu)))
        costs[name] = 2.0 * (h / r) * math.sin(math.radians(di) / 2.0)

    result = plane_change(a, di, e, argp_deg=argp)
    assert result.delta_v_at_ascending_node == pytest.approx(costs["ascending node"], rel=1e-9)
    assert result.delta_v_at_descending_node == pytest.approx(costs["descending node"], rel=1e-9)
    assert result.optimal_location == "descending node"
    assert result.optimal_delta_v == pytest.approx(min(costs.values()), rel=1e-9)


def test_a_circular_orbit_reports_a_node_not_an_apogee() -> None:
    result = plane_change(7000.0, 5.0)
    assert result.optimal_location == "node"
    assert result.optimal_delta_v == pytest.approx(2 * math.sqrt(MU_EARTH / 7000.0) * math.sin(math.radians(2.5)))
