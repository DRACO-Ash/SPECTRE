"""Flying a plan's burns, and searching a method's choices for its cheapest approach.

Every epoch is fixed: CLAUDE.md, after 0.6.8 failed the App Store's Test
stage on a test whose geometry moved with the hour.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro import targeting
from spectre.astro.flight import fly
from spectre.astro.maneuvers import (
    Burn,
    InterceptSolution,
    cw_drift_intercept,
    lambert_intercept,
    plane_change_intercept,
)
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

_START = datetime(2026, 10, 28, 22, 0, tzinfo=UTC)
_GEO_DAY_S = 86164.0


class TestFlyingTheBurns:
    def test_a_lambert_transfer_arrives(self) -> None:
        sol = lambert_intercept(_RED_GEO, _BLUE_GEO, _START, tof_s=6 * 3600.0, coast_s=0.0)
        assert fly(sol, _RED_GEO, _BLUE_GEO).closest_km < 1.0

    def test_cw_drift_does_not_reach_a_target_600_km_away(self) -> None:
        """It reported the 10 km it was asked for; 1 m/s moves it about 22 km in 6 hours."""
        sol = cw_drift_intercept(_RED_GEO, _BLUE_GEO, _START, desired_drift_km=10.0, time_s=6 * 3600.0)
        assert sol.miss_distance_km == pytest.approx(10.0)
        assert fly(sol, _RED_GEO, _BLUE_GEO).closest_km > 500.0

    def test_an_instant_plan_is_flown_for_a_revolution(self) -> None:
        sol = plane_change_intercept(_RED_GEO, _BLUE_GEO, _START)
        flight = fly(sol, _RED_GEO, _BLUE_GEO)
        assert flight.closest_km == pytest.approx(sol.miss_distance_km, rel=0.02)
        assert flight.closest_at > sol.burns[0].epoch

    def test_no_burns_is_the_coast_alone(self) -> None:
        sol = InterceptSolution(method="x", departure_epoch=_START, arrival_epoch=_START + timedelta(hours=6))
        assert fly(sol, _RED_GEO, _BLUE_GEO).closest_km > 500.0

    def test_a_burn_to_escape_is_refused(self) -> None:
        from spectre.astro.propagator import TLEOrbit

        v = TLEOrbit(_RED_GEO).propagate(_START).v
        burn = Burn(burn_number=1, epoch=_START, delta_v=v * 1.0, delta_v_mag=float(np.linalg.norm(v)))
        sol = InterceptSolution(method="x", burns=[burn], departure_epoch=_START, arrival_epoch=_START)
        with pytest.raises(ValueError, match="escape"):
            fly(sol, _RED_GEO, _BLUE_GEO)


class TestTheChoices:
    def test_a_geo_revolution(self) -> None:
        assert targeting.revolution_s(_RED_GEO, _START) == pytest.approx(_GEO_DAY_S, rel=0.01)

    def test_burn_points_start_now_and_run_in_time_order(self) -> None:
        points = targeting.burn_points(_RED_GEO, _START, _GEO_DAY_S)
        assert points[0] == (targeting.NOW, _START)
        assert [p[1] for p in points] == sorted(p[1] for p in points)
        assert {"Apogee", "Perigee"} <= {p[0] for p in points}
        assert all(_START <= at <= _START + timedelta(seconds=_GEO_DAY_S) for _, at in points)

    def _points(self) -> list[tuple[str, datetime]]:
        return [(targeting.NOW, _START), ("Apogee", _START + timedelta(hours=3))]

    def test_burn_and_time_of_flight(self) -> None:
        found = targeting.choices((targeting.BURN, targeting.TOF), self._points(), _START, _GEO_DAY_S)
        assert len(found) == 2 * len(targeting.TOF_FRACTIONS)
        assert {c.coast_s for c in found} == {0.0, 3 * 3600.0}
        assert min(c.tof_s or 0 for c in found) == pytest.approx(0.25 * _GEO_DAY_S)

    def test_revolutions_and_hops(self) -> None:
        revs = targeting.choices((targeting.BURN, targeting.REVS), self._points(), _START, _GEO_DAY_S)
        hops = targeting.choices((targeting.BURN, targeting.HOP), self._points(), _START, _GEO_DAY_S)
        assert {c.revolutions for c in revs} == set(targeting.REVOLUTIONS)
        assert {c.hops for c in hops} == set(targeting.HOPS)
        assert all(c.tof_s is None and c.hops is None for c in revs)

    def test_without_the_burn_axis_only_now(self) -> None:
        assert [c.burn_point for c in targeting.choices((), self._points(), _START, _GEO_DAY_S)] == [targeting.NOW]


def _sol(dv_km_s: float) -> InterceptSolution:
    return InterceptSolution(method="x", total_delta_v=dv_km_s, departure_epoch=_START, arrival_epoch=_START)


class TestTheSearchKeepsTheRightPlan:
    """Each choice's coast stands for the plan's cost; the measure says how close it came."""

    def _run(self, plans: dict[float, tuple[float, int]], radius: float = 50.0) -> targeting.Targeted:
        candidates = [targeting.Choice(targeting.NOW, _START, coast) for coast in plans]

        def measure(sol: InterceptSolution) -> tuple[float, datetime]:
            km, hour = plans[sol.total_delta_v]
            return km, _START + timedelta(hours=hour)

        return targeting.search(lambda c: _sol(c.coast_s), measure, candidates, radius)

    def test_an_approach_beats_a_cheaper_plan_that_misses(self) -> None:
        kept = self._run({0.001: (600.0, 1), 0.020: (10.0, 1)})
        assert (kept.solution.total_delta_v, kept.approach) == (0.020, True)

    def test_the_cheapest_approach(self) -> None:
        assert self._run({0.030: (1.0, 1), 0.010: (40.0, 1)}).solution.total_delta_v == pytest.approx(0.010)

    def test_equal_cost_goes_to_the_sooner_arrival(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, h) for h in (5.0, 2.0, 9.0)]

        def solve(c: targeting.Choice) -> InterceptSolution:
            later = _START + timedelta(hours=c.coast_s)
            return InterceptSolution(method="x", total_delta_v=0.01, departure_epoch=later, arrival_epoch=later)

        kept = targeting.search(solve, lambda s: (5.0, s.departure_epoch), candidates, 50.0)
        assert kept.choice.coast_s == pytest.approx(2.0)
        assert (kept.tried, kept.refused) == (3, 0)

    def test_with_no_approach_the_closest_is_kept(self) -> None:
        kept = self._run({0.001: (600.0, 1), 0.002: (300.0, 1)})
        assert (kept.solution.total_delta_v, kept.approach) == (0.002, False)

    def test_the_radius_decides(self) -> None:
        assert not self._run({0.001: (49.6, 1)}, radius=5.0).approach

    def test_refusals_are_counted_and_the_last_reason_kept(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, c) for c in (1.0, 2.0, 3.0)]

        def solve(c: targeting.Choice) -> InterceptSolution:
            if c.coast_s < 3.0:
                raise ValueError(f"degenerate at {c.coast_s:g}")
            return _sol(0.001)

        kept = targeting.search(solve, lambda _s: (1.0, _START), candidates, 50.0)
        assert (kept.tried, kept.refused) == (3, 2)
        with pytest.raises(ValueError, match="degenerate at 2"):
            targeting.search(solve, lambda _s: (1.0, _START), candidates[:2], 50.0)

    def test_an_unmeasurable_plan_is_refused(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, 1.0)]
        with pytest.raises(ValueError, match="could not be computed"):
            targeting.search(lambda _c: _sol(0.001), lambda _s: (math.nan, _START), candidates, 50.0)
