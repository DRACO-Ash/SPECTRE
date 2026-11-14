"""The edges of sizing our burn, and the red arc it is sized against (SPC-121, review of 0.16.0).

A burn exactly at the target needs nothing, a burn exactly at the closest approach cannot open it, a refusal names
the closest approach it was decided on, and a sampled row's burn is sized against red flown with the
hypothesis's nominal burn as stated: its magnitude along its RIC direction, at its epoch.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from spectre.astro import monte_carlo
from spectre.astro.monte_carlo import (
    BlueBurn,
    ManoeuvreHypothesis,
    SeparationWindow,
    burnt_arc,
    elset_state,
    nominal_red_arc,
    rk45_arc,
)
from spectre.astro.response_burn import (
    BurnAxis,
    BurnRefusal,
    BurnRequest,
    SizedBurn,
    rk45_approach,
    rk45_pair,
    size_against,
)
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE

_LEO = SeparationWindow(EPOCH, COPLANAR_LEO.horizon_s)


def _pair() -> object:
    pair = rk45_pair(COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, _LEO)
    assert not isinstance(pair, str)
    return pair


@pytest.fixture(scope="module")
def leo() -> tuple[object, float, float]:
    """The coplanar_leo pair on RK45, with its no-burn miss and TCA."""
    pair = _pair()
    before = rk45_approach(pair.red, pair.blue, _LEO)  # type: ignore[attr-defined]
    return pair, before.approach.miss_km, before.approach.tca_s


class TestTheEdges:
    def test_a_target_exactly_at_the_miss_needs_no_burn(self, leo: tuple[object, float, float]) -> None:
        pair, miss, _tca = leo
        sized = size_against(pair, _LEO, BurnRequest("1", 0.0, miss, 0.05, BurnAxis.CHEAPEST))  # type: ignore[arg-type]
        assert isinstance(sized, SizedBurn)
        assert sized.burn is None and sized.trials == 0 and sized.reached

    def test_a_burn_exactly_at_the_tca_cannot_open_it(self, leo: tuple[object, float, float]) -> None:
        pair, _miss, tca = leo
        refused = size_against(pair, _LEO, BurnRequest("1", tca, 20.0, 0.05, BurnAxis.CHEAPEST))  # type: ignore[arg-type]
        assert isinstance(refused, BurnRefusal)
        assert refused.reason == "after_tca" and refused.trials == 0

    def test_an_after_tca_refusal_names_the_tca_it_was_decided_on(self, leo: tuple[object, float, float]) -> None:
        pair, _miss, tca = leo
        refused = size_against(pair, _LEO, BurnRequest("1", tca + 60.0, 20.0, 0.05, BurnAxis.CHEAPEST))  # type: ignore[arg-type]
        assert isinstance(refused, BurnRefusal)
        assert refused.tca_s == tca

    def test_other_refusals_name_no_tca(self) -> None:
        pair = _pair()
        refused = size_against(pair, _LEO, BurnRequest("1", _LEO.span_s, 20.0, 0.05, BurnAxis.CHEAPEST))  # type: ignore[arg-type]
        assert isinstance(refused, BurnRefusal)
        assert refused.reason == "after_window" and refused.tca_s is None


class TestTheNominalRedArc:
    def test_red_flies_the_stated_magnitude_along_the_stated_direction(self) -> None:
        """The components give only the direction: (3, 4, 0) scaled to 8 m/s, at the window start."""
        window = SeparationWindow(EPOCH, 3600.0)
        start = elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert start is not None
        hypothesis = ManoeuvreHypothesis(
            epoch_utc=EPOCH, delta_v_magnitude_km_s=0.008, delta_v_radial=0.003, delta_v_in_track=0.004,
            delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=start.state_eci_km, bstar_post=start.bstar,
        )
        unburnt = rk45_arc(start.state_eci_km, window.span_s, start.bstar)
        assert unburnt is not None
        by_hand = burnt_arc(unburnt, BlueBurn(0.0, (0.0048, 0.0064, 0.0)), window.span_s, start.bstar)
        nominal = nominal_red_arc(hypothesis, window)
        assert by_hand is not None and nominal is not None
        for t in (600.0, 1800.0, 3600.0):
            assert np.linalg.norm(nominal(t)[:3] - by_hand(t)[:3]) < 1e-3
        assert np.linalg.norm(nominal(3600.0)[:3] - unburnt(3600.0)[:3]) > 10.0

    def test_red_burns_at_the_hypothesis_epoch(self) -> None:
        """Ten minutes into the window, red is still on its unburnt arc before then and off it after."""
        window = SeparationWindow(EPOCH, 3600.0)
        at = elset_state(PLANE_CHANGE.red_tle, EPOCH + timedelta(minutes=10))
        assert at is not None
        hypothesis = ManoeuvreHypothesis(
            epoch_utc=EPOCH + timedelta(minutes=10), delta_v_magnitude_km_s=0.008, delta_v_radial=0.0,
            delta_v_in_track=1.0, delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=at.state_eci_km,
            bstar_post=at.bstar,
        )
        nominal = nominal_red_arc(hypothesis, window)
        assert nominal is not None
        assert np.linalg.norm(nominal(600.0)[:3] - at.state_eci_km[:3]) < 1e-6
        speed_change = np.linalg.norm(nominal(600.0 + 1e-3)[3:] - nominal(600.0 - 1e-3)[3:])
        assert speed_change == pytest.approx(0.008, abs=1e-5)


class TestTheFailurePaths:
    """What the engine does when an arc cannot be had: it says so, and never raises into the sample loop."""

    def _hypothesis(self) -> ManoeuvreHypothesis:
        at = elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert at is not None
        return ManoeuvreHypothesis(
            epoch_utc=EPOCH, delta_v_magnitude_km_s=0.001, delta_v_radial=0.0, delta_v_in_track=1.0,
            delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=at.state_eci_km, bstar_post=at.bstar,
        )

    def test_a_burn_at_or_after_the_end_leaves_the_arc(self) -> None:
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        arc = rk45_arc(blue.state_eci_km, 600.0, blue.bstar)
        assert arc is not None
        assert burnt_arc(arc, BlueBurn(600.0, (0.0, 0.001, 0.0)), 600.0, blue.bstar) is arc

    @pytest.mark.parametrize("failure", [None, ValueError("singular"), ZeroDivisionError()])
    def test_a_red_arc_that_cannot_be_integrated_is_none(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception | None,
    ) -> None:
        def _unburnt(*_args: object) -> None:
            if failure is not None:
                raise failure

        monkeypatch.setattr(monte_carlo, "_unburnt_arc", _unburnt)
        assert nominal_red_arc(self._hypothesis(), SeparationWindow(EPOCH, 3600.0)) is None

    def test_a_burnt_blue_arc_that_fails_numerically_fails_the_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raises(*_args: object) -> None:
            raise FloatingPointError

        monkeypatch.setattr(monte_carlo, "burnt_arc", _raises)
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        arc = rk45_arc(blue.state_eci_km, 600.0, blue.bstar)
        assert arc is not None
        found = monte_carlo._burnt_blue(arc, BlueBurn(0.0, (0.0, 0.001, 0.0)), SeparationWindow(EPOCH, 600.0), 1e-4)
        assert found == monte_carlo._FAILED
