"""The V-bar and H-bar hop rows record every burn, cost what their burns add up to, and are flown (V0.40 review).

The hop solvers listed only a sequence's first and last burn, while their cost counted every hop. On the GEO pair
736 km apart, three V-bar hops read 6.42 km, arriving, at 26.84 m/s, though the two burns recorded totalled 8.95 m/s
and flew to 498.7 km (target ahead) or 467.1 km (behind); the rows were never flown, though the page said every
approach was. Now every burn is recorded (a V-bar hop's stop and the next hop's entry, falling at one instant, are
one burn), the burns add up to the cost, and each hop row is flown through spectre.astro.flight.fly like every red
approach, its arrival judged on the flown figure. A row whose flown figure does not come within the approach
distance reads "No approach".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.astro import flight, targeting
from spectre.astro.along_track import shift_along_track
from spectre.domain import realism
from spectre.domain.manoeuvre_evidence import shipped_evidence
from spectre.web.routes import maneuver
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

_START = datetime(2026, 3, 1, tzinfo=UTC)
#: The ISS and a copy of it 50 km further along its orbit.
_ISS = ("1 25544U 98067A   26060.00000000  .00016717  00000-0  10270-3 0  9994\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49815327    17")
_ISS_AHEAD = shift_along_track(_ISS, 50.0)
#: Red then target, for each regime and side.
_PAIRS = {
    "GEO, target ahead": (_RED_GEO, _BLUE_GEO, "GEO"),
    "GEO, target behind": (_BLUE_GEO, _RED_GEO, "GEO"),
    "LEO, target ahead": (_ISS, _ISS_AHEAD, "LEO"),
    "LEO, target behind": (_ISS_AHEAD, _ISS, "LEO"),
}
_HOPS = (maneuver.InterceptMethod.VBAR_HOP, maneuver.InterceptMethod.HBAR_HOP)


def _row(pair: str, method: maneuver.InterceptMethod) -> dict[str, Any]:
    red, blue, regime = _PAIRS[pair]
    evidence = shipped_evidence()
    args = maneuver._InterceptArgs(
        red, blue, _START, 0.0, 21600.0, 0.0, evidence.fleet.largest_window_m_s,
        maneuver._Shaping(hops=3, search=False),
    )
    budget, _why = realism.realistic_budget_m_s(None, evidence)
    raw = maneuver._batch(args, "RED", "BLUE", budget)
    judged = maneuver._Assessing(regime, args.max_dv_m_s, None, "RED", evidence, red, blue)
    return next(i for i in maneuver._items_from_solutions(raw, judged) if i["method"] is method)


@pytest.mark.parametrize("method", _HOPS, ids=lambda m: m.value)
@pytest.mark.parametrize("pair", list(_PAIRS))
def test_each_hop_row_is_flown_and_its_burns_are_its_cost(pair: str, method: maneuver.InterceptMethod) -> None:
    red, blue, _ = _PAIRS[pair]
    row = _row(pair, method)
    result, t = row["result"], row["targeting"]
    assert result is not None and t is not None
    burns = result.burns
    assert len(burns) == (4 if method is maneuver.InterceptMethod.VBAR_HOP else 3), "every burn of three hops"
    assert sum(b.delta_v_m_s for b in burns) == pytest.approx(result.total_delta_v_m_s, rel=1e-9)
    solved = maneuver._run_intercept(method, red, blue, _START, 0.0, 21600.0, 0.0, 171.8,
                                     shaping=maneuver._Shaping(hops=3))
    assert t["closest_km"] == pytest.approx(flight.fly(solved, red, blue).miss_km, abs=1e-6)
    radius = maneuver.approach_radius_km(0.0)
    assert t["approach"] is (targeting.arrives(t["closest_km"], radius) and not t["already_within"])


@pytest.mark.parametrize("pair", ["GEO, target ahead", "GEO, target behind"])
def test_three_v_bar_hops_flown_arrive_at_geo_from_either_side(pair: str) -> None:
    """The linear model puts the sequence 6.4 km from the target; flown, it arrives within the 50 km radius."""
    t = _row(pair, maneuver.InterceptMethod.VBAR_HOP)["targeting"]
    assert t["closest_km"] < realism.CLOSE_APPROACH_KM / 2.0
    assert t["approach"]


@pytest.mark.parametrize("pair", list(_PAIRS))
def test_an_h_bar_hop_against_an_along_track_gap_reads_no_approach(pair: str) -> None:
    """The pairs are co-planar: the H-bar swing covers no along-track gap, and flown it does not arrive."""
    row = _row(pair, maneuver.InterceptMethod.HBAR_HOP)
    assert not row["counts"]
    assert not row["targeting"]["approach"]


def test_the_flight_basis_is_stated_for_leo_where_the_model_mix_moves_the_target() -> None:
    """In LEO the flown figure reads red two-body against the target on SGP4, and over 1.5 orbits the two part by
    tens of km: with no burn the ISS copy behind closes from 50 km to 4.2 km. The ahead row is "Already within", so
    a hop there is not counted as reaching anything; the figure is the flown one, whatever the linear model said."""
    ahead = _row("LEO, target ahead", maneuver.InterceptMethod.VBAR_HOP)
    assert ahead["targeting"]["already_within"] and not ahead["counts"]
    assert flight.FLIGHT_BASIS == "flown from the plan's burns: two-body for red between burns, SGP4 for the target"
