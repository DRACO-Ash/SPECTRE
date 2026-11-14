"""Flying a plan's burns, and searching a method's choices for its cheapest approach (SPC-234).

Ported from charming-dirac d3447e2 onto the one flown-miss path 0.33.0 built: spectre.astro.flight.fly flies every
burn of a plan through maneuvers.flown_approach, the function plane change, phasing and the R-bar hop already fly
their single burn with, so a solver's own figure and the Intercept Engine's flown figure cannot come to differ.

Every epoch is fixed, so no test's geometry moves with the hour.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro import maneuvers, targeting
from spectre.astro.constants import MU_EARTH
from spectre.astro.flight import fly
from spectre.astro.kepler import propagate_two_body
from spectre.astro.maneuvers import (
    Burn,
    InterceptSolution,
    cw_drift_intercept,
    cw_radial_intercept,
    hohmann_intercept,
    lambert_intercept,
    plane_change_intercept,
)
from spectre.astro.propagator import TLEOrbit
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE

_START = datetime(2026, 3, 1, tzinfo=UTC)
_GEO_DAY_S = 86164.0
_DENSE_STEP_S = 10.0


def _dense_least(sol: InterceptSolution, red_tle: str, blue_tle: str, span_s: float) -> float:
    """The least separation, sampled every _DENSE_STEP_S from the first burn, flying every burn: the reference."""
    burns = sorted(sol.burns, key=lambda b: b.epoch)
    start = burns[0].epoch
    sv = TLEOrbit(red_tle).propagate(start)
    r, v, at = sv.r, sv.v, start
    target = TLEOrbit(blue_tle)
    least = math.inf
    pending = list(burns)
    for k in range(int(span_s / _DENSE_STEP_S) + 1):
        when = start + timedelta(seconds=k * _DENSE_STEP_S)
        while pending and pending[0].epoch <= when:
            burn = pending.pop(0)
            r, v = propagate_two_body(r, v, (burn.epoch - at).total_seconds(), MU_EARTH)
            v, at = v + burn.delta_v, burn.epoch
        here, _ = propagate_two_body(r, v, (when - at).total_seconds(), MU_EARTH)
        least = min(least, float(np.linalg.norm(here - target.propagate(when).r)))
    return least


class TestFlyingTheBurns:
    def test_a_lambert_transfer_arrives(self) -> None:
        sol = lambert_intercept(_RED_GEO, _BLUE_GEO, _START, tof_s=6 * 3600.0, coast_s=0.0)
        flight = fly(sol, _RED_GEO, _BLUE_GEO)
        assert flight.miss_km < 1.0
        assert sol.departure_epoch <= flight.at <= sol.arrival_epoch

    def test_cw_drift_does_not_reach_a_target_736_km_away(self) -> None:
        """It reports the 10 km it was asked for; 1 m/s moves it a few tens of km in 6 hours."""
        sol = cw_drift_intercept(_RED_GEO, _BLUE_GEO, _START, desired_drift_km=10.0, time_s=6 * 3600.0)
        assert sol.miss_distance_km == pytest.approx(10.0)
        assert fly(sol, _RED_GEO, _BLUE_GEO).miss_km > 500.0

    def test_every_burn_of_a_two_burn_plan_is_flown(self) -> None:
        sol = hohmann_intercept(_RED_GEO, _BLUE_GEO, _START)
        span_s = (sol.arrival_epoch - sol.burns[0].epoch).total_seconds()
        assert len(sol.burns) == 2
        assert fly(sol, _RED_GEO, _BLUE_GEO).miss_km == pytest.approx(
            _dense_least(sol, _RED_GEO, _BLUE_GEO, span_s), abs=0.5)

    def test_an_instant_plan_is_flown_for_a_revolution_as_its_solver_flies_it(self) -> None:
        tles = (PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle)
        sol = plane_change_intercept(*tles, EPOCH)
        flight = fly(sol, *tles)
        assert flight.miss_km == pytest.approx(sol.miss_distance_km, abs=0.05)
        period = timedelta(minutes=TLEOrbit(PLANE_CHANGE.red_tle).period_minutes)
        assert sol.burns[0].epoch <= flight.at <= sol.burns[0].epoch + period

    def test_no_burns_is_the_coast_alone(self) -> None:
        sol = InterceptSolution(method="x", departure_epoch=_START, arrival_epoch=_START + timedelta(hours=6))
        assert fly(sol, _RED_GEO, _BLUE_GEO).miss_km > 500.0


class TestOneFlownMissPath:
    """The solvers that fly their own burn and the Intercept Engine fly through the same function (0.33.0)."""

    def test_the_r_bar_hop_s_own_figure_is_the_engine_s(self) -> None:
        sol = cw_radial_intercept(_RED_GEO, _BLUE_GEO, _START, desired_separation_km=5.0, time_s=6 * 3600.0)
        assert fly(sol, _RED_GEO, _BLUE_GEO).miss_km == pytest.approx(sol.miss_distance_km, abs=1e-6)

    def test_fly_searches_through_the_shared_closest_approach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[float] = []
        real = maneuvers.closest_approach

        def counted(separation, span_s, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(span_s)
            return real(separation, span_s, **kwargs)

        monkeypatch.setattr(maneuvers, "closest_approach", counted)
        sol = lambert_intercept(_RED_GEO, _BLUE_GEO, _START, tof_s=6 * 3600.0)
        fly(sol, _RED_GEO, _BLUE_GEO)
        assert calls == [pytest.approx(6 * 3600.0)]

    def test_inside_miss_not_read_nothing_is_flown(self) -> None:
        sol = lambert_intercept(_RED_GEO, _BLUE_GEO, _START, tof_s=6 * 3600.0)
        with maneuvers.miss_not_read():
            flight = fly(sol, _RED_GEO, _BLUE_GEO)
        assert math.isnan(flight.miss_km) and flight.at is None and not flight.computed


class TestAFlownSearchThatCannotRunIsNotComputed:
    """SPC-238: closest_approach raises with no finite sample or past its sample limit; the method must not fail."""

    def test_past_the_sample_limit_the_r_bar_hop_still_solves(self) -> None:
        # 120 days of LEO revolutions at 96 samples each is past closest_approach's 100,000.
        tles = (PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle)
        sol = cw_radial_intercept(*tles, EPOCH, desired_separation_km=5.0, time_s=120 * 86400.0)
        assert sol.total_delta_v > 0.0
        assert math.isnan(sol.miss_distance_km)

    def test_no_finite_separation_is_not_computed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def nothing_finite(*_a: object, **_k: object) -> None:
            raise ValueError("closest_approach: no finite separation in the window")

        monkeypatch.setattr(maneuvers, "closest_approach", nothing_finite)
        sol = maneuvers.phasing_intercept(_RED_GEO, _BLUE_GEO, _START)
        assert math.isnan(sol.miss_distance_km)
        assert math.isnan(fly(sol, _RED_GEO, _BLUE_GEO).miss_km)

    def test_a_propagator_fault_still_fails_the_method(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the search's own refusal is read as not computed. KeplerConvergenceError is a ValueError raised by
        the propagator inside the separation, and it must not be hidden as "not computed" (review of SPC-234)."""
        from spectre.astro.kepler import KeplerConvergenceError

        def diverges(*_a: object, **_k: object) -> None:
            raise KeplerConvergenceError("universal anomaly did not converge for dt=60.0 s")

        monkeypatch.setattr(maneuvers, "propagate_two_body", diverges)
        with pytest.raises(KeplerConvergenceError, match="did not converge"):
            maneuvers.phasing_intercept(_RED_GEO, _BLUE_GEO, _START)

    def test_an_escape_burn_is_flown_over_its_span(self) -> None:
        red = TLEOrbit(_RED_GEO).propagate(_START)
        escape = red.v / red.v_mag * 2.0
        burn = Burn(burn_number=1, epoch=_START, delta_v=escape, delta_v_mag=2.0)
        sol = InterceptSolution(method="x", burns=[burn], departure_epoch=_START,
                                arrival_epoch=_START + timedelta(seconds=600.0))
        assert fly(sol, _RED_GEO, _BLUE_GEO).miss_km < 100.0


class TestArrivalIsJudgedWithATolerance:
    """A flown Lambert miss lands micrometres either side of its aim point, so a plain <= rejected half of them."""

    @pytest.mark.parametrize(("km", "radius"), [
        (0.100000440, 0.1), (0.100008311, 0.1), (0.1, 0.1), (20.0000004, 20.0), (50.0009, 50.0), (0.0, 0.0),
    ])
    def test_on_the_knife_edge_it_arrives(self, km: float, radius: float) -> None:
        assert targeting.arrives(km, radius)

    @pytest.mark.parametrize(("km", "radius"), [(0.1015, 0.1), (50.0011, 50.0), (math.nan, 50.0), (math.inf, 50.0)])
    def test_beyond_the_tolerance_or_not_computed_it_does_not(self, km: float, radius: float) -> None:
        assert not targeting.arrives(km, radius)

    def test_the_search_uses_it(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, 0.001)]
        kept = targeting.search(lambda c: _sol(c.coast_s), lambda _s: (0.100008311, _START), candidates, 0.1)
        assert kept.approach


class TestAPlanAlreadyWithinIsNotAnApproach:
    """The no-burn baseline over the same window: a target already inside the radius is not reached by burning."""

    def test_a_baseline_inside_the_radius_is_already_within(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, 0.001)]
        kept = targeting.search(lambda c: _sol(c.coast_s), lambda _s: (5.0, _START, 18.0), candidates, 50.0)
        assert (kept.approach, kept.already_within) == (False, True)

    def test_a_baseline_outside_it_leaves_an_approach(self) -> None:
        candidates = [targeting.Choice(targeting.NOW, _START, 0.001)]
        kept = targeting.search(lambda c: _sol(c.coast_s), lambda _s: (5.0, _START, 700.0), candidates, 50.0)
        assert (kept.approach, kept.already_within) == (True, False)

    def test_the_baseline_flies_no_burn_over_the_plan_s_window(self) -> None:
        from spectre.astro.flight import baseline

        sol = lambert_intercept(_RED_GEO, _BLUE_GEO, _START, tof_s=6 * 3600.0)
        coast = baseline(sol, _RED_GEO, _BLUE_GEO)
        assert 700.0 < coast.miss_km < 740.0, "the GEO pair is about 736 km apart with no burn"
        assert sol.departure_epoch <= coast.at <= sol.arrival_epoch


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

        def measure(sol: InterceptSolution) -> tuple[float, datetime | None]:
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

    def test_with_no_approach_the_closest_is_kept_and_labelled(self) -> None:
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

    def test_a_plan_whose_miss_was_not_computed_is_kept_but_never_an_approach(self) -> None:
        """SPC-238: NaN is not a reason to fail the method, and never reads as arriving."""
        candidates = [targeting.Choice(targeting.NOW, _START, 1.0)]
        kept = targeting.search(lambda _c: _sol(0.001), lambda _s: (math.nan, None), candidates, 50.0)
        assert math.isnan(kept.closest_km) and kept.approach is False

    def test_a_computed_miss_beats_one_not_computed_whatever_the_cost(self) -> None:
        kept = self._run({0.001: (math.nan, 1), 0.050: (900.0, 1)})
        assert kept.solution.total_delta_v == pytest.approx(0.050) and not kept.approach

    def test_the_cheapest_plan_that_arrives_stops_the_flying(self) -> None:
        """Plans are measured cheapest first; once one arrives, nothing dearer can beat it."""
        measured: list[float] = []
        plans = {0.010: 600.0, 0.020: 10.0, 0.030: 1.0, 0.040: 1.0}
        candidates = [targeting.Choice(targeting.NOW, _START, dv) for dv in plans]

        def measure(sol: InterceptSolution) -> tuple[float, datetime | None]:
            measured.append(sol.total_delta_v)
            return plans[sol.total_delta_v], _START

        kept = targeting.search(lambda c: _sol(c.coast_s), measure, candidates, 50.0)
        assert kept.solution.total_delta_v == pytest.approx(0.020)
        assert measured == [0.010, 0.020]
        assert kept.tried == len(plans)
