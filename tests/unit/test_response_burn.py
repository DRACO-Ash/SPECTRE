"""Our burn on the blue asset, sized to a target separation by propagation (SPC-121).

SGP4 cannot take an impulsive burn, so a figure that includes our burn propagates both objects by the Monte Carlo
engine's RK45 with J2 and drag from their SGP4 states at the scenario epoch, and blue burns from its own RK45 arc:
one model on both sides of every subtraction. The size is searched, not assumed: the manoeuvre library's
Clohessy-Wiltshire size is a first guess, both senses are flown, the size doubles until the target is reached or
the budget is spent and then halves back to within 1 %. The library's guess for coplanar_leo is about 0.23 m/s;
the burn that reaches 20 km is about 3.1 m/s, because a prograde burn moves the encounter as well as the miss.

Reference element sets: tests/unit/_decision_reference.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from spectre.astro import response_burn
from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import ElsetApproach
from spectre.astro.monte_carlo import (
    BlueBurn,
    ManoeuvreHypothesis,
    SeparationWindow,
    elset_state,
    run_separation_series,
)
from spectre.astro.response_burn import (
    MAX_SIZING_TRIALS,
    RESPONSE_PROPAGATOR,
    BurnAxis,
    BurnRefusal,
    BurnRequest,
    Rk45Pair,
    Rk45Plan,
    SizedBurn,
    burnt_approach,
    elset_response_plan,
    rk45_approach,
    rk45_pair,
    size_against,
)
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE

_BUDGET = 0.05     # km/s, 50 m/s
_LEO = SeparationWindow(EPOCH, COPLANAR_LEO.horizon_s)


def _request(target: float, *, at_s: float = 0.0, budget: float = _BUDGET, axis: BurnAxis = BurnAxis.CHEAPEST) -> BurnRequest:
    return BurnRequest("F1", at_s, target, budget, axis)


def _plan(case: Any, window: SeparationWindow, *requests: BurnRequest) -> Rk45Plan:
    plan = elset_response_plan(case.red_tle, case.blue_tle, window, requests)
    assert isinstance(plan, Rk45Plan)
    return plan


def _sized(plan: Rk45Plan) -> SizedBurn:
    sized = plan.responses[0]
    assert isinstance(sized, SizedBurn), sized
    return sized


@pytest.fixture(scope="module")
def leo_20() -> SizedBurn:
    return _sized(_plan(COPLANAR_LEO, _LEO, _request(20.0)))


class TestTheSameModelOnBothSides:
    def test_a_zero_burn_reproduces_the_no_burn_approach_exactly(self) -> None:
        """15."""
        pair = rk45_pair(COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, _LEO)
        assert not isinstance(pair, response_burn.ElsetFailure)
        before = rk45_approach(pair.red, pair.blue, _LEO)
        after = burnt_approach(pair, _LEO, BlueBurn(0.0, (0.0, 0.0, 0.0)))
        assert after == before
        assert before.propagator == RESPONSE_PROPAGATOR

    def test_the_no_burn_figure_is_rk45_for_both(self) -> None:
        plan = _plan(COPLANAR_LEO, _LEO, _request(5.0))
        assert plan.before.propagator == RESPONSE_PROPAGATOR
        assert plan.before.approach.miss_km == pytest.approx(10.0057, abs=0.001)


class TestSizing:
    def test_coplanar_leo_to_20_km_with_a_burn_at_the_epoch(self, leo_20: SizedBurn) -> None:
        """16: 3.085 m/s retrograde in-track, where the library's Clohessy-Wiltshire guess is about 0.23 m/s."""
        assert leo_20.burn is not None
        dv = np.asarray(leo_20.burn.delta_v_ric_km_s)
        assert np.linalg.norm(dv) == pytest.approx(0.003085, rel=0.01)
        assert dv[1] < 0.0 and dv[0] == dv[2] == 0.0
        assert leo_20.axis is BurnAxis.IN_TRACK and leo_20.from_library
        assert leo_20.reached and leo_20.trials <= MAX_SIZING_TRIALS
        assert leo_20.after.approach.miss_km >= 20.0
        assert leo_20.before.approach.miss_km == pytest.approx(10.0057, abs=0.001)
        assert leo_20.lead_s == pytest.approx(leo_20.before.approach.tca_s)

    def test_both_senses_are_flown(self, leo_20: SizedBurn) -> None:
        """17: 1 m/s prograde at the epoch closes the miss to 9.705 km, so the sense must be retrograde."""
        pair = rk45_pair(COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, _LEO)
        assert not isinstance(pair, response_burn.ElsetFailure)
        prograde = burnt_approach(pair, _LEO, BlueBurn(0.0, (0.0, 0.001, 0.0)))
        assert prograde.approach.miss_km == pytest.approx(9.705, abs=0.01)
        assert leo_20.sense == -1

    def test_a_target_already_met_spends_nothing(self) -> None:
        """18."""
        sized = _sized(_plan(COPLANAR_LEO, _LEO, _request(5.0)))
        assert sized.burn is None and sized.trials == 0 and sized.reached
        assert sized.after == sized.before

    def test_over_budget_burns_the_budget_and_reports_short(self) -> None:
        """19."""
        sized = _sized(_plan(COPLANAR_LEO, _LEO, _request(500.0, budget=0.001)))
        assert sized.burn is not None and not sized.reached
        assert np.linalg.norm(sized.burn.delta_v_ric_km_s) == pytest.approx(0.001)
        assert sized.after.approach.miss_km < 500.0

    def test_an_operator_axis_is_kept(self) -> None:
        sized = _sized(_plan(PLANE_CHANGE, SeparationWindow(EPOCH, 3600.0), _request(20.0, axis=BurnAxis.RADIAL)))
        assert sized.burn is not None and sized.axis is BurnAxis.RADIAL and not sized.from_library
        assert sized.burn.delta_v_ric_km_s[1] == sized.burn.delta_v_ric_km_s[2] == 0.0
        assert sized.after.approach.miss_km >= 20.0

    def test_the_minimum_at_the_window_end_is_flagged(self) -> None:
        """22: GEO drift-in to 150 km over 48 h ends still closing, at 152.67 km on the last instant."""
        window = SeparationWindow(EPOCH, GEO_DRIFT_IN.horizon_s, GEO_DRIFT_IN.step_s)
        sized = _sized(_plan(GEO_DRIFT_IN, window, _request(150.0)))
        assert sized.reached
        assert sized.after.approach.at_window_edge
        assert sized.after.approach.tca_s == GEO_DRIFT_IN.horizon_s
        assert sized.after.approach.miss_km == pytest.approx(152.67, abs=0.5)

    def test_trials_stay_within_the_cap_from_a_tiny_library_guess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """23: a 0.01 m/s guess starts from the budget over 64 and doubles."""
        guess = SimpleNamespace(strategy="along_track", delta_v=1e-5)
        monkeypatch.setattr(response_burn, "collision_avoidance", lambda *_: SimpleNamespace(best=guess))
        ticks: list[tuple[int, int]] = []
        plan = elset_response_plan(
            COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, _LEO, (_request(40.0),),
            tick=lambda _key, done, total: ticks.append((done, total)),
        )
        assert isinstance(plan, Rk45Plan)
        sized = _sized(plan)
        assert sized.reached and sized.trials <= MAX_SIZING_TRIALS
        assert ticks == [(k, MAX_SIZING_TRIALS) for k in range(1, sized.trials + 1)]


class TestRefusals:
    def test_a_burn_after_the_tca_is_refused(self) -> None:
        """20: coplanar_leo's closest approach is at about 14,484 s."""
        refused = _plan(COPLANAR_LEO, _LEO, _request(20.0, at_s=15_000.0)).responses[0]
        assert isinstance(refused, BurnRefusal)
        assert refused[:3] == ("F1", "after_tca", 0)
        assert refused.tca_s == pytest.approx(14_484.0, abs=1.0)

    @pytest.mark.parametrize("at_s", [COPLANAR_LEO.horizon_s, COPLANAR_LEO.horizon_s + 1.0])
    def test_a_burn_at_or_after_the_window_end_is_refused(self, at_s: float) -> None:
        """21."""
        assert _plan(COPLANAR_LEO, _LEO, _request(20.0, at_s=at_s)).responses[0] == BurnRefusal("F1", "after_window", 0)

    def test_a_reentering_burnt_arc_is_refused(self) -> None:
        """24: blue 101 km up, where drag brings any burnt arc below the 100 km floor."""
        r = 6378.137 + 101.0
        blue_state = np.array([r, 0.0, 0.0, 0.0, (398600.4418 / r) ** 0.5, 0.0])

        def blue(_t: float) -> np.ndarray:
            return blue_state.copy()

        def red(t: float) -> np.ndarray:
            return blue_state + np.array([1.0 + abs(t - 1800.0) / 100.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        refused = size_against(Rk45Pair(red, blue, 1e-3), SeparationWindow(EPOCH, 3600.0), _request(50.0))
        assert isinstance(refused, BurnRefusal)
        assert refused.reason == "reentered" and refused.trials == 1


class TestTheSeriesTakesOurBurn:
    def _nominal(self) -> tuple[ManoeuvreHypothesis, Any]:
        blue, red = elset_state(PLANE_CHANGE.blue_tle, EPOCH), elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert blue is not None and red is not None
        hypothesis = ManoeuvreHypothesis(
            epoch_utc=EPOCH, delta_v_magnitude_km_s=0.0, delta_v_radial=0.0, delta_v_in_track=0.0,
            delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=red.state_eci_km,
            delta_v_magnitude_1sigma_km_s=0.0, delta_v_pointing_1sigma_deg=0.0, epoch_1sigma_seconds=0.0,
            bstar_post=0.0, bstar_1sigma=0.0, n_samples=3,
        )
        return hypothesis, blue

    def test_each_burn_is_paired_with_the_samples(self) -> None:
        """25: a zero burn at the window start equals the no-burn figure; a real one moves it; a re-entering one
        fails that burn alone."""
        hypothesis, blue = self._nominal()
        burns = (
            BlueBurn(0.0, (0.0, 0.0, 0.0)), BlueBurn(0.0, (0.005, 0.0, 0.0)), BlueBurn(0.0, (0.0, -3.0, 0.0)),
        )
        series = run_separation_series(hypothesis, blue, SeparationWindow(EPOCH, 3600.0), blue_burns=burns)
        assert [b.burn for b in series.after_burns] == list(burns)
        zero, radial, down = series.after_burns
        assert zero.approaches == series.approaches and zero.closing_speeds_km_s == series.closing_speeds_km_s
        assert zero.stats.p5 == series.miss_km_p5
        assert len(radial.approaches) == 3 and radial.n_failed == 0
        assert abs(radial.approaches[0].miss_km - series.approaches[0].miss_km) > 5.0   # 5 m/s outward closes it to 4.8 km
        assert down.approaches == () and down.n_failed == 3
        assert series.n_failed == 0

    def test_no_burn_leaves_the_series_as_it_was(self) -> None:
        hypothesis, blue = self._nominal()
        series = run_separation_series(hypothesis, blue, SeparationWindow(EPOCH, 3600.0))
        assert series.after_burns == ()
        assert isinstance(series.approaches[0], ClosestApproach)

    def test_a_burn_before_the_window_is_refused(self) -> None:
        hypothesis, blue = self._nominal()
        with pytest.raises(ValueError, match="our burn"):
            run_separation_series(
                hypothesis, blue, SeparationWindow(EPOCH, 3600.0), blue_burns=(BlueBurn(-1.0, (0.0, 0.0, 0.0)),),
            )


def test_the_figure_is_an_elset_approach() -> None:
    plan = _plan(PLANE_CHANGE, SeparationWindow(EPOCH, 3600.0), _request(20.0))
    assert isinstance(plan.before, ElsetApproach)
    assert plan.before.approach.miss_km == pytest.approx(10.4036, abs=0.001)
