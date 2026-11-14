"""The V-bar hop fires toward the target's side, and its miss figure reads the side it moves to (SPC-237).

In the linear (Clohessy-Wiltshire) model an outward radial impulse drifts the chaser backwards along V-bar, by
4 x dv / n after half an orbit. The hop always fired its entry burn outward (+b_hat), whichever side the target was
on, so for a target ahead the recorded burn moved red away from it. Flown through spectre.astro.flight.fly on the GEO
pair 736 km apart (0.39.0): with the target ahead the closest approach stayed at 736.0 km, no closer than 735.7 km
with no burn at all, and red ended 1,004.6 km away; with the target behind it closed to 467.1 km. The 0.33.0 miss
figure took abs() of the along-track gap, so both read 6.4 km. The correction burn at arrival fired the opposite way
to the entry burn, which doubled red's radial rate there (-4.47 to -8.94 m/s) instead of stopping it.

Now every burn is signed by the target's side, inward for a target ahead, outward for one behind, and each hop's
stop fires the same way in the local frame as its entry, so it stops the radial drift the entry started. Since the
V0.40 review every burn of the sequence is recorded (n hops, n + 1 burns: a stop and the next entry at one instant
are one burn) and the miss is the flown one, so a hop the wrong way could no longer read as closing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro import flight, maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.propagator import StateVector, TLEOrbit, state_to_keplerian
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

_START = datetime(2026, 3, 1, tzinfo=UTC)
#: Red then target: blue is 1 degree ahead of red in the same GEO orbit, so swapping them puts the target behind.
_AHEAD = (_RED_GEO, _BLUE_GEO)
_BEHIND = (_BLUE_GEO, _RED_GEO)
_SIDES = {"target ahead": _AHEAD, "target behind": _BEHIND}


def _on_axis_km(red: str, blue: str) -> float:
    """The target's along-track offset from red at the start, km: positive ahead."""
    sv_red, sv_blue = TLEOrbit(red).propagate(_START), TLEOrbit(blue).propagate(_START)
    return float(np.dot(sv_blue.r - sv_red.r, sv_red.v / sv_red.v_mag))


@pytest.mark.parametrize("side", list(_SIDES))
def test_the_flown_hop_closes_on_the_target_from_either_side(side: str) -> None:
    red, blue = _SIDES[side]
    for n_hops in (1, 3):
        sol = maneuvers.vbar_hop_intercept(red, blue, _START, n_hops=n_hops)
        flown, still = flight.fly(sol, red, blue).miss_km, flight.baseline(sol, red, blue).miss_km
        # Every burn flown: 0.39.0 flew three hops to 736.0 km (ahead) and 467.1 km (behind); now about 23 km.
        assert flown < 30.0 < still - 600.0, f"{side}, {n_hops} hop(s): flown {flown:.1f} km, unburnt {still:.1f} km"


def test_the_solutions_miss_is_the_flown_one() -> None:
    for side, (red, blue) in _SIDES.items():
        sol = maneuvers.vbar_hop_intercept(red, blue, _START)
        assert sol.miss_distance_km == pytest.approx(flight.fly(sol, red, blue).miss_km, abs=1e-6), side


@pytest.mark.parametrize("n_hops", [1, 3, 5])
def test_every_burn_is_recorded_and_the_burns_are_the_cost(n_hops: int) -> None:
    """n hops are n + 1 burns: an entry, n - 1 stops each merged with the next entry, and a last stop."""
    sol = maneuvers.vbar_hop_intercept(*_AHEAD, _START, n_hops=n_hops)
    sizes = [b.delta_v_mag for b in sol.burns]
    assert len(sizes) == n_hops + 1
    assert sum(sizes) == pytest.approx(sol.total_delta_v, rel=1e-12)
    assert sizes[1:-1] == pytest.approx([2.0 * sizes[0]] * (n_hops - 1), rel=1e-12)
    assert sizes[-1] == pytest.approx(sizes[0], rel=1e-12)
    gaps = {round((b.epoch - a.epoch).total_seconds(), 3) for a, b in zip(sol.burns, sol.burns[1:], strict=False)}
    assert len(gaps) <= 1, "half an orbit apart"


def test_the_h_bar_hop_records_every_burn_alternating_and_the_burns_are_the_cost() -> None:
    sol = maneuvers.hbar_hop_intercept(*_AHEAD, _START, n_hops=3)
    assert len(sol.burns) == 3
    assert sum(b.delta_v_mag for b in sol.burns) == pytest.approx(sol.total_delta_v, rel=1e-12)
    normals = [b.dv_normal for b in sol.burns]
    assert normals[0] * normals[1] < 0.0 < normals[0] * normals[2]


def test_the_entry_burn_points_inward_for_a_target_ahead_and_outward_for_one_behind() -> None:
    assert _on_axis_km(*_AHEAD) > 700.0
    assert _on_axis_km(*_BEHIND) < -700.0
    ahead = maneuvers.vbar_hop_intercept(*_AHEAD, _START).burns[0]
    behind = maneuvers.vbar_hop_intercept(*_BEHIND, _START).burns[0]
    assert ahead.dv_radial < 0.0 < behind.dv_radial
    assert ahead.delta_v_mag == pytest.approx(behind.delta_v_mag, rel=1e-6)


@pytest.mark.parametrize("side", list(_SIDES))
def test_the_last_stop_leaves_red_on_a_circular_orbit_again(side: str) -> None:
    """Before the last stop red is on the eccentric orbit the hop put it on; after it, near-circular as it began."""
    red, blue = _SIDES[side]
    sol = maneuvers.vbar_hop_intercept(red, blue, _START, n_hops=3)
    sv = TLEOrbit(red).propagate(_START)
    eccentricities = []
    for burn in sol.burns:
        r, v = propagate_two_body(sv.r, sv.v, (burn.epoch - sv.epoch).total_seconds(), MU_EARTH)
        sv = StateVector(epoch=burn.epoch, r=r, v=v + burn.delta_v)
        eccentricities.append(state_to_keplerian(sv).ecc)
    assert eccentricities[-2] > 1e-3
    assert eccentricities[-1] < 3e-4
