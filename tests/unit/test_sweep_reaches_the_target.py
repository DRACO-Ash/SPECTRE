"""A sweep row is an approach to the target, at the burn it names.

0.6.6 in service: the threat sweep listed TJS-3-class plane changes at
"perigee", "apogee" and "now", each about 89 m/s and graded ANNOYANCE. A pure
plane change can only be flown where the orbit crosses the target's plane, and
the solver did wait for that node, hours later, but the row kept the search
point's name and time. Its miss distance was hard-coded to 0 km while the red
object, now coplanar, stayed 610 km from the target. The same was true of every
method: burns were priced whether or not they arrived, so a 0 m/s Hohmann ending
607 km away was ranked as a benign approach.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro.maneuvers import Burn, InterceptSolution, plane_change_intercept
from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

_START = datetime(2026, 10, 28, 22, 0, tzinfo=UTC)
_TARGET = ThreatTarget("BLUE-GEO", "", "blue", None)


def _checksummed(line: str) -> str:
    body = line[:68]
    return body + str(sum(int(c) if c.isdigit() else int(c == "-") for c in body) % 10)


def _tilted(tle: str, by_deg: float) -> str:
    """*tle* with its inclination raised by *by_deg*."""
    line1, line2 = tle.splitlines()
    inclination = float(line2[8:16])
    return f"{line1}\n{_checksummed(line2[:8] + f'{inclination + by_deg:8.4f}' + line2[16:])}"


def _solution(burn_at: datetime, miss_km: float = 0.0) -> InterceptSolution:
    burn = Burn(burn_number=1, epoch=burn_at, delta_v=np.zeros(3), delta_v_mag=0.0889)
    return InterceptSolution(
        method="plane_change", burns=[burn], total_delta_v=0.0889,
        departure_epoch=burn_at, arrival_epoch=burn_at, miss_distance_km=miss_km,
    )


class TestAPlaneChangeIsWhereAndWhenItBurns:
    def test_the_row_names_the_node_and_its_time(self) -> None:
        burn_at = _START + timedelta(hours=11.9)
        entry = threat._sol_to_entry(_solution(burn_at), _TARGET, _START, "perigee", "plane_change", "GEO")
        assert entry.burn_location == "rel_node", "a plane change at perigee is not what was computed"
        assert entry.burn_epoch == burn_at

    def test_a_burn_at_the_search_point_keeps_its_name(self) -> None:
        entry = threat._sol_to_entry(_solution(_START), _TARGET, _START, "apogee", "hohmann", "GEO")
        assert (entry.burn_location, entry.burn_epoch) == ("apogee", _START)

    def test_search_points_that_reach_the_same_burn_give_one_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        burn_at = _START + timedelta(hours=11.9)
        monkeypatch.setattr(threat, "_SWEEP_METHODS", (("plane_change", lambda **_k: _solution(burn_at), {}),))
        request = threat._SweepRequest(
            red_tle=_RED_GEO, target_tle=_BLUE_GEO, target=_TARGET, max_dv_m_s=500.0, regime="GEO",
        )
        points = [("now", _START), ("perigee", _START + timedelta(hours=1)), ("apogee", _START + timedelta(hours=4))]
        entries = threat._sweep_all_methods(request, points)
        assert len(entries) == 1


class TestAPlaneChangeDoesNotCloseTheGap:
    def test_the_miss_is_the_along_track_gap_not_zero(self) -> None:
        """1.66 degrees at GEO costs 89 m/s and leaves the target about 610 km away."""
        sol = plane_change_intercept(_RED_GEO, _tilted(_BLUE_GEO, 1.66), _START)
        assert sol.total_delta_v * 1000.0 == pytest.approx(89.0, abs=1.0)
        assert sol.miss_distance_km > 500.0

    def test_so_the_sweep_refuses_it_and_says_why(self) -> None:
        refusals: dict[str, str] = {}
        request = threat._SweepRequest(
            red_tle=_RED_GEO, target_tle=_tilted(_BLUE_GEO, 1.66), target=_TARGET, max_dv_m_s=500.0, regime="GEO",
        )
        entries = threat._sweep_all_methods(request, [("now", _START)], refusals)
        assert "plane_change" not in {e.method for e in entries}
        assert "km from the target" in refusals["plane_change"]
        assert "hohmann" not in {e.method for e in entries}, "co-altitude, 600 km apart: a Hohmann arrives nowhere"


class TestTheApproachRule:
    @pytest.mark.parametrize(("miss_km", "refused"), [(0.0, False), (50.0, False), (50.1, True), (math.nan, True)])
    def test_the_close_approach_radius(self, miss_km: float, refused: bool) -> None:
        assert bool(threat._not_an_approach(_solution(_START, miss_km), 500.0)) is refused

    def test_the_budget_is_still_applied_first(self) -> None:
        reason = threat._not_an_approach(_solution(_START), 50.0)
        assert reason is not None and "budget" in reason


class TestEveryMissIsAMiss:
    """Phasing reported the radial gap alone, and the hops their travel distance."""

    def test_phasing_reports_where_the_chaser_actually_arrives(self) -> None:
        from spectre.astro.constants import MU_EARTH
        from spectre.astro.maneuvers import _coast, phasing_intercept
        from spectre.astro.propagator import TLEOrbit

        sol = phasing_intercept(_RED_GEO, _BLUE_GEO, _START)
        burn = sol.burns[0]
        arrived = _coast(TLEOrbit(_RED_GEO).propagate(burn.epoch), burn.delta_v, sol.arrival_epoch, MU_EARTH)
        target = TLEOrbit(_BLUE_GEO).propagate(sol.arrival_epoch)
        assert sol.miss_distance_km == pytest.approx(float(np.linalg.norm(arrived.r - target.r)), rel=1e-9)

    @pytest.mark.parametrize(("separation", "advance", "expected"), [
        ((600.0, 0.0, 0.0), 600.0, 0.0),     # along-track gap, fully hopped
        ((600.0, 3.0, 4.0), 600.0, 5.0),     # the off-axis 3-4-5 is left
        ((600.0, 0.0, 0.0), 0.0, 600.0),     # hopping on another axis leaves it all
    ])
    def test_a_hop_leaves_what_its_axis_does_not_cover(
        self, separation: tuple[float, float, float], advance: float, expected: float,
    ) -> None:
        from spectre.astro.maneuvers import _hop_residual_km

        residual = _hop_residual_km(np.array(separation), np.array([1.0, 0.0, 0.0]), advance)
        assert residual == pytest.approx(expected)

    def test_an_hbar_hop_does_not_close_an_along_track_gap(self) -> None:
        from spectre.astro.maneuvers import hbar_hop_intercept

        sol = hbar_hop_intercept(_RED_GEO, _BLUE_GEO, _START)
        assert sol.miss_distance_km > 500.0, "it reported 3 km, its travel, from a target 600 km away"
