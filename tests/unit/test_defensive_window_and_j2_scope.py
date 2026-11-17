"""The defensive search's window edge, and where J2 drift applies (0.47.0 physics re-review).

S1: the closest approach after a defensive burn was searched within 10 minutes of the assumed TCA and the window-edge
separation was shown as the closest approach when the encounter lay outside: a LEO head-on COLA whose TCA was assumed
610 s late read 151.44 km for 0.27 km. The search now widens to a quarter revolution of the faster orbit, and an edge
it still cannot leave is never presented as a closest approach.

S2: J2 drift planned confident burns between near-equatorial orbits, whose RAAN means nothing. N1: an already-closed
gap read "not reachable". N3: Evasion's TCA is the manoeuvre start, not start plus coast. N4: the J2 plan is checked
against a brute-force search on an independent nodal-rate formula, and the uncapped plan against HEAD field for field.

Every reference here is independent of the code under test: scipy integrates the burn, scipy's bounded minimiser finds
the closest approach, and the nodal rate is written out from its formula.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

from spectre.astro import maneuvers
from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.tactical import j2_drift_plan
from spectre.domain.models import InterceptMethod
from spectre.web.routes import maneuver
from tests.unit.test_engine_honest_labels import _TCA, _Circular, _Inclined, _result, _summary


def _use(monkeypatch: pytest.MonkeyPatch, red: object, blue: object) -> None:
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])


def _reference(sol: maneuvers.InterceptSolution, burner: _Circular, other: _Circular, half_s: float,
               step_s: float) -> float:
    """The closest approach within *half_s* of the assumed TCA, after the burn, the burner flying it in scipy."""
    burn = sol.burns[0]
    start = burner.propagate(burn.epoch)
    to_tca = (sol.arrival_epoch - burn.epoch).total_seconds()

    def f(_t: float, s: np.ndarray) -> list[float]:
        return [*s[3:], *(-MU_EARTH * s[:3] / np.linalg.norm(s[:3]) ** 3)]

    flown = solve_ivp(f, (0.0, to_tca + half_s + step_s), np.concatenate([start.r, start.v + burn.delta_v]),
                      dense_output=True, rtol=1e-12, atol=1e-10).sol

    def separation(t: float) -> float:
        return float(np.linalg.norm(flown(t)[:3] - other.propagate(burn.epoch + timedelta(seconds=t)).r))

    grid = np.arange(max(to_tca - half_s, 0.0), to_tca + half_s + step_s / 2, step_s)
    k = int(np.argmin([separation(t) for t in grid]))
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    return float(minimize_scalar(separation, bounds=(lo, hi), method="bounded", options={"xatol": 1e-7}).fun)


class TestTheSearchLeavesTheWindowEdge:
    def test_a_late_assumed_tca_in_leo_head_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The review's case: TCA assumed 610 s late, the true encounter outside +/-10 min."""
        red, blue = _Circular(7000.0, 180.0, 0.0), _Circular(7000.0, 0.0, 0.0)
        _use(monkeypatch, red, blue)
        sol = maneuvers.cola_intercept("RED", "BLUE", _TCA + timedelta(seconds=610.0), desired_miss_km=1.0,
                                       time_before_tca_s=3600.0)
        assert sol.edge_floor_km is None
        assert sol.search_window_s is not None and sol.search_window_s > maneuvers.DEFENCE_WINDOW_S
        assert sol.miss_distance_km == pytest.approx(_reference(sol, red, blue, 2000.0, 1.0), abs=2e-3)
        assert sol.miss_distance_km < 1.0, "the 151 km edge separation was read as the closest approach"

    def test_a_geo_shallow_crossing_hours_away(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 0.1 deg GEO crossing whose TCA was assumed 5.4 h early: the encounter is hours outside +/-10 min."""
        red, blue = _Circular(42166.0, 0.1, 0.0), _Circular(42164.0, 0.0, 0.0)
        _use(monkeypatch, red, blue)
        sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA - timedelta(hours=5.4), desired_miss_km=10.0,
                                          time_before_tca_s=3600.0, fuel_budget_km_s=0.05)
        assert sol.edge_floor_km is None
        assert sol.search_window_s is not None and sol.search_window_s > 3600.0
        expected = _reference(sol, blue, red, sol.search_window_s, 20.0)
        assert sol.miss_distance_km == pytest.approx(expected, abs=2e-3)

    def test_an_encounter_beyond_every_window_is_not_a_closest_approach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Co-orbital, 5 deg apart and 10 km higher: still opening at the widened edge, so no closest approach."""
        red, blue = _Circular(7010.0, 51.6, 5.0), _Circular(7000.0, 51.6, 0.0)
        _use(monkeypatch, red, blue)
        sol = maneuvers.cola_intercept("RED", "BLUE", _TCA, desired_miss_km=1.0, time_before_tca_s=3600.0)
        assert math.isnan(sol.miss_distance_km)
        assert sol.edge_floor_km is not None and sol.search_window_s is not None
        # At the edge the separation is still changing by metres a second, so the floor agrees to 10 m.
        assert sol.edge_floor_km == pytest.approx(_reference(sol, red, blue, sol.search_window_s, 1.0), abs=1e-2)

    def test_evasion_never_counts_an_edge_as_reaching_the_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A cheap candidate whose search ended at the edge, 50 km out, against a dearer one that truly reaches 12 km."""
        _use(monkeypatch, _Circular(7000.0, 60.0, 0.0), _Circular(7000.0, 0.0, 0.0))

        def judged(_self: object, _sv: object, dv: np.ndarray, _mu: float) -> maneuvers.DefenceApproach:
            cheap = float(np.linalg.norm(dv)) < 0.0005
            return (maneuvers.DefenceApproach(math.nan, 1457.0, 50.0) if cheap
                    else maneuvers.DefenceApproach(12.0, 600.0))

        monkeypatch.setattr(maneuvers._Encounter, "closest_after", judged)
        sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, time_before_tca_s=3600.0,
                                          fuel_budget_km_s=0.5)
        assert sol.edge_floor_km is None and sol.miss_distance_km == 12.0

    def test_the_row_says_so_and_sorts_it_with_those_not_computed(self) -> None:
        result = _result(InterceptMethod.COLA, miss=math.nan)
        result.search_window_s, result.edge_floor_km = 1457.0, 586.33
        cell = maneuver._miss_cell(result)
        assert cell["text"] == "≥586.3" and cell["sort"] == ""
        summary = _summary(result)
        assert "no closest approach to BLUE-01 within ±24 min of the assumed TCA" in summary
        assert "separation at least 586.3 km at the window edge; check the TCA" in summary
        assert "closest approach to BLUE-01 after the burn" not in summary


class TestEvasionsTcaIsTheManoeuvreStart:
    def test_the_words_follow_the_method(self) -> None:
        assert "(the manoeuvre start)" in _summary(_result(InterceptMethod.EVASION))
        assert "(manoeuvre start plus coast)" in _summary(_result(InterceptMethod.COLA))
        assert "(manoeuvre start plus coast)" in _summary(_result(InterceptMethod.FORMATION))


class TestJ2DriftOnlyWhereRaanMeansSomething:
    def test_near_equatorial_leo_is_not_applicable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0.01 deg inclination, 170 deg of 'RAAN gap': planned at 4.9 m/s before."""
        _use(monkeypatch, _Inclined(6378.137 + 424.0, 0.5, 170.0), _Inclined(6378.137 + 420.0, 0.5, 0.0))
        with pytest.raises(maneuvers.NotApplicableError, match="within 1 deg of the equator"):
            maneuvers.j2_drift_intercept("RED", "BLUE", _TCA)

    def test_geo_planes_a_hundredth_of_a_degree_apart_are_aligned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0.05 deg GEO pair, 30 deg of 'RAAN gap': planned at 722.8 m/s before; the planes are 0.026 deg apart."""
        _use(monkeypatch, _Inclined(42164.0, 0.05, 30.0), _Inclined(42164.0, 0.05, 0.0))
        with pytest.raises(maneuvers.PlanesAlignedError, match="already aligned"):
            maneuvers.j2_drift_intercept("RED", "BLUE", _TCA)

    def test_the_batch_row_reads_the_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def aligned(**_: object) -> maneuvers.InterceptSolution:
            raise maneuvers.PlanesAlignedError("the planes are already aligned: 0.026 deg apart")

        monkeypatch.setitem(maneuver._COAST_ONLY_SOLVERS, InterceptMethod.J2_DRIFT, aligned)
        monkeypatch.setattr(maneuver, "_ALL_METHODS_SEQUENCE", [InterceptMethod.J2_DRIFT])
        args = maneuver._InterceptArgs("RED", "BLUE", _TCA, 0.0, 3600.0, 0.0, 100.0)
        (outcome,) = maneuver._run_all_methods(args, "RED-01", "BLUE-01", maneuver._Plan([], 0.0, 0.0, 50.0))
        assert outcome.verdict == "ALIGNED"

    def test_a_closed_gap_is_reached_at_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """N1: no RAAN gap, planes 1.4 deg apart in inclination: natural time 0, not 'not reachable'."""
        plan = j2_drift_plan(R_EARTH + 424.0, 0.0005, 51.6, R_EARTH + 420.0, 0.0005, 53.0, 0.0,
                             cap_days=maneuvers.J2_DRIFT_CAP_DAYS)
        assert plan.convergence_time_days == 0.0 and plan.accel_convergence_days == 0.0
        _use(monkeypatch, _Inclined(R_EARTH + 424.0, 51.6, 0.0), _Inclined(R_EARTH + 420.0, 53.0, 0.0))
        sol = maneuvers.j2_drift_intercept("RED", "BLUE", _TCA)
        assert sol.arrival_epoch == _TCA and not sol.burns


def _nodal_rate_deg_day(a_km: float, ecc: float, inc_deg: float) -> float:
    """dOmega/dt = -3/2 n J2 (R/p)^2 cos i, written out here, not the code's j2_raan_rate."""
    n = math.sqrt(MU_EARTH / a_km ** 3)
    p = a_km * (1.0 - ecc ** 2)
    return math.degrees(-1.5 * n * J2_EARTH * (R_EARTH / p) ** 2 * math.cos(math.radians(inc_deg))) * 86400.0


class TestJ2PlanAgainstBruteForce:
    """N4: the smallest altitude change that closes the gap within the cap, found by brute force."""

    _A_T = R_EARTH + 420.0

    @staticmethod
    def _smallest(a_c: float, a_t: float, inc: float, gap: float, cap: float) -> float:
        rate_t = _nodal_rate_deg_day(a_t, 0.0005, inc)
        best = math.inf
        for dalt in np.arange(R_EARTH + 200.0 - a_c, 2000.0, 0.01):
            diff = _nodal_rate_deg_day(a_c + dalt, 0.0005, inc) - rate_t
            if diff == 0.0:
                continue
            days = -gap / diff
            if days <= 0.0:
                days = (360.0 - abs(gap)) / abs(diff)
            if days <= cap and abs(dalt) < abs(best):
                best = float(dalt)
        return best

    @pytest.mark.parametrize(("above_km", "gap"), [(4.0, 170.0), (4.0, -170.0), (6.0, 120.0), (6.0, -170.0),
                                                   (8.0, 170.0)])
    def test_the_change_is_the_smallest_that_meets_the_cap(self, above_km: float, gap: float) -> None:
        """Every pair here is one whose halved convergence is past the cap; one that fits keeps HEAD's halving."""
        cap = maneuvers.J2_DRIFT_CAP_DAYS
        plan = j2_drift_plan(self._A_T + above_km, 0.0005, 51.6, self._A_T, 0.0005, 51.6, gap, cap_days=cap)
        assert plan.convergence_time_days / 2.0 > cap, "precondition: halving is past the cap"
        smallest = self._smallest(self._A_T + above_km, self._A_T, 51.6, gap, cap)
        assert plan.accel_convergence_days <= cap
        assert plan.accel_altitude_change_km == pytest.approx(smallest, abs=0.02)

    def test_the_long_way_round_when_it_needs_less(self) -> None:
        """4 km above, 170 deg ahead: lowering 22 km closes 170 deg; raising 16.5 km closes the other 190 deg."""
        plan = j2_drift_plan(self._A_T + 4.0, 0.0005, 51.6, self._A_T, 0.0005, 51.6, 170.0,
                             cap_days=maneuvers.J2_DRIFT_CAP_DAYS)
        assert plan.accel_altitude_change_km > 0.0
        diff = (_nodal_rate_deg_day(self._A_T + 4.0 + plan.accel_altitude_change_km, 0.0005, 51.6)
                - _nodal_rate_deg_day(self._A_T, 0.0005, 51.6))
        assert diff * plan.accel_convergence_days == pytest.approx(190.0, rel=1e-6)


#: HEAD's j2_drift_plan (before 0.47.0), field for field, for five pairs: with no cap the plan must not move.
_HEAD = [
    ((R_EARTH + 424.0, 0.0005, 51.6, R_EARTH + 420.0, 0.0005, 51.6, 170.0),
     {"raan_rate_chaser_deg_day": -4.94083794249239, "raan_rate_target_deg_day": -4.9510205295260015,
      "differential_rate_deg_day": 0.010182587033611412, "delta_raan_deg": 170.0,
      "convergence_time_days": 18659.305279968088, "accel_altitude_change_km": -11.131563218029441,
      "accel_convergence_days": 9329.652639984044, "accel_delta_v": 0.006271340054714969, "method": "j2_drift"}),
    ((R_EARTH + 424.0, 0.0005, 51.6, R_EARTH + 420.0, 0.0005, 51.6, -120.0),
     {"raan_rate_chaser_deg_day": -4.94083794249239, "raan_rate_target_deg_day": -4.9510205295260015,
      "differential_rate_deg_day": 0.010182587033611412, "delta_raan_deg": -120.0,
      "convergence_time_days": 11784.824387348266, "accel_altitude_change_km": 4.010612995910378,
      "accel_convergence_days": 5892.412193674133, "accel_delta_v": 0.0022557428052669692, "method": "j2_drift"}),
    ((R_EARTH + 700.0, 0.001, 97.5, R_EARTH + 500.0, 0.001, 97.4, 30.0),
     {"raan_rate_chaser_deg_day": 0.9033299891028312, "raan_rate_target_deg_day": 0.9854129675043317,
      "differential_rate_deg_day": -0.08208297840150047, "delta_raan_deg": 30.0,
      "convergence_time_days": 365.4838138701312, "accel_altitude_change_km": 195.30055755241756,
      "accel_convergence_days": 182.7419069350656, "accel_delta_v": 0.10143041532205466, "method": "j2_drift"}),
    ((R_EARTH + 550.0, 0.0, 53.0, R_EARTH + 550.0, 0.0, 53.0, 12.0),
     {"raan_rate_chaser_deg_day": -4.48920725826226, "raan_rate_target_deg_day": -4.48920725826226,
      "differential_rate_deg_day": 0.0, "delta_raan_deg": 12.0, "convergence_time_days": math.inf,
      "accel_altitude_change_km": -29.118453006946766, "accel_convergence_days": 180.0,
      "accel_delta_v": 0.01599019034495175, "method": "j2_drift"}),
    ((R_EARTH + 35786.0, 0.0002, 5.0, R_EARTH + 35786.0, 0.0002, 4.0, -45.0),
     {"raan_rate_chaser_deg_day": -0.01336310164049328, "raan_rate_target_deg_day": -0.013381470331110402,
      "differential_rate_deg_day": 1.8368690617122027e-05, "delta_raan_deg": -45.0,
      "convergence_time_days": 2449820.7813492217, "accel_altitude_change_km": 16.574105561201577,
      "accel_convergence_days": 1224910.3906746109, "accel_delta_v": 0.0006041240870686693, "method": "j2_drift"}),
]


@pytest.mark.parametrize(("args", "head"), _HEAD, ids=["170", "-120", "sso", "inf", "geo"])
def test_without_a_cap_the_plan_is_heads_field_for_field(args: tuple[float, ...], head: dict[str, object]) -> None:
    now = dataclasses.asdict(j2_drift_plan(*args))
    assert now.keys() == head.keys()
    for key, value in head.items():
        assert now[key] == (pytest.approx(value, rel=1e-12) if isinstance(value, float) else value), key
