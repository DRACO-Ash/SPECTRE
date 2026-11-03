"""The closest approach of two element sets, both on SGP4, with no burn (SPC-120).

The Decision Engine's computed closest approach: both bound orbits are
propagated by SGP4 from their element sets, the separation is searched every
60 s by the shared helper (spectre/astro/closest_approach.py) and each local
minimum is refined to 0.01 s, as the access search does (audit F-115). A
failed SGP4 instant refuses the call, naming its side, rather than reading as
infinite, because an infinity could hide the minimum.

The F-115 pair (tests/unit/test_scenario_closest_approach.py) closes at about
15 km/s with a 300 km miss: the brute-force SGP4 reference at 0.1 s puts it at
299.981 km, 3,599.00 s into the window.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import numpy as np
import pytest

from spectre.astro import elset_approach, monte_carlo, propagator
from spectre.astro.elset_approach import (
    ELSET_PROPAGATOR,
    ElsetApproach,
    ElsetFailure,
    elset_closest_approach,
)
from spectre.astro.monte_carlo import ManoeuvreHypothesis, SeparationWindow, rk45_sgp4_gap_km
from spectre.astro.propagator import StateVector, TLEOrbit
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE, ReferenceCase
from tests.unit.test_decision_reference_cases import _monte_carlo_nominal
from tests.unit.test_scenario_closest_approach import _BLUE, _EPOCH, _RED

_SIX_HOURS = SeparationWindow(start_utc=_EPOCH, span_s=6 * 3600.0)
_PC_HOUR = SeparationWindow(start_utc=EPOCH, span_s=3600.0)


def _failing(tle: str, *, after_s: float = 0.0, only_at_s: float | None = None) -> type[TLEOrbit]:
    """A TLEOrbit whose propagation of *tle* fails after *after_s*, or only at *only_at_s*, into the window."""

    class Failing(TLEOrbit):
        def propagate(self, epoch: datetime) -> StateVector:
            t = (epoch - _EPOCH).total_seconds()
            fails = t > after_s if only_at_s is None else abs(t - only_at_s) < 1e-4
            if self.line2 == tle.splitlines()[1] and fails:
                raise RuntimeError("SGP4 error code 6")
            return super().propagate(epoch)

    return Failing


class TestTheComputedClosestApproach:
    def test_it_finds_the_f115_crossing(self) -> None:
        """A1: 299.98 km at 3,599.0 s, to 0.01 km and 0.1 s, where a fixed 60 s grid alone lands up to 30 s off."""
        found = elset_closest_approach(_RED, _BLUE, _SIX_HOURS)
        assert isinstance(found, ElsetApproach)
        assert found.approach.miss_km == pytest.approx(299.98, abs=0.01)
        assert found.approach.tca_s == pytest.approx(3599.0, abs=0.1)
        assert found.approach.at_window_edge is False
        assert found.window == _SIX_HOURS
        assert found.propagator == ELSET_PROPAGATOR == "SGP4 for both orbits, from their element sets, with no burn"

    def test_the_closing_speed_is_the_relative_speed_at_closest_approach(self) -> None:
        """Counter-rotating orbits at 420 and 720 km pass at about 15 km/s."""
        found = elset_closest_approach(_RED, _BLUE, _SIX_HOURS)
        assert isinstance(found, ElsetApproach)
        at = found.approach.tca_utc(_EPOCH)
        red, blue = TLEOrbit(_RED).propagate(at), TLEOrbit(_BLUE).propagate(at)
        assert found.closing_speed_km_s == pytest.approx(float(np.linalg.norm(red.v - blue.v)), rel=1e-12)
        assert 14.5 < found.closing_speed_km_s < 15.5

    def test_the_plane_change_reference_is_reproduced(self) -> None:
        found = elset_closest_approach(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, SeparationWindow(_EPOCH, 3600.0))
        assert isinstance(found, ElsetApproach)
        assert abs(found.approach.miss_km - PLANE_CHANGE.miss_km) <= PLANE_CHANGE.miss_tol_km
        assert abs(found.approach.tca_s - PLANE_CHANGE.tca_s) <= PLANE_CHANGE.tca_tol_s


class TestARefusalNamesItsSide:
    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_a_failed_sgp4_instant_refuses_and_names_its_side(self, side: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A2: the orbit fails from 2 h on; read as infinite, the crossing at 1 h would still have been reported."""
        tle = _RED if side == "red" else _BLUE
        monkeypatch.setattr(elset_approach, "TLEOrbit", _failing(tle, after_s=7200.0))
        assert elset_closest_approach(_RED, _BLUE, _SIX_HOURS) == ElsetFailure(side=side, reason="propagation")  # type: ignore[arg-type]

    def test_one_failed_grid_instant_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elset_approach, "TLEOrbit", _failing(_RED, only_at_s=10_800.0))
        assert elset_closest_approach(_RED, _BLUE, _SIX_HOURS) == ElsetFailure(side="red", reason="propagation")

    def test_a_failure_at_the_closest_approach_itself_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The closing speed is read at the TCA; an orbit that fails there is refused, not given a speed."""
        found = elset_closest_approach(_RED, _BLUE, _SIX_HOURS)
        assert isinstance(found, ElsetApproach)
        monkeypatch.setattr(elset_approach, "TLEOrbit", _failing(_BLUE, only_at_s=found.approach.tca_s))
        assert elset_closest_approach(_RED, _BLUE, _SIX_HOURS) == ElsetFailure(side="blue", reason="propagation")

    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_an_element_set_that_does_not_parse_is_refused(self, side: str) -> None:
        red, blue = ("not an element set", _BLUE) if side == "red" else (_RED, "not an element set")
        assert elset_closest_approach(red, blue, _SIX_HOURS) == ElsetFailure(side=side, reason="unparsable")  # type: ignore[arg-type]


class TestThePropagatorGap:
    @pytest.mark.parametrize(
        ("case", "measured_km"), [(COPLANAR_LEO, 0.405), (GEO_DRIFT_IN, 22.62)], ids=["coplanar_leo", "geo_drift_in"],
    )
    def test_the_gap_bounds_the_difference_between_the_two_propagators_minima(
        self, case: ReferenceCase, measured_km: float,
    ) -> None:
        """A3: SGP4 on both against RK45 on both, over the case's horizon from its epoch.

        Measured: coplanar_leo 0.405 km over 6 h, the minima 0.0002 km apart; geo_drift_in 22.62 km over 48 h
        (about 11.3 km an object), the minima 0.001 km apart, because the error is largely common to both.
        """
        window = SeparationWindow(EPOCH, case.horizon_s)
        computed = elset_closest_approach(case.red_tle, case.blue_tle, window)
        assert isinstance(computed, ElsetApproach)
        nominal = _monte_carlo_nominal(case, 0.0)
        gap = rk45_sgp4_gap_km(case.red_tle, case.blue_tle, window)
        assert gap is not None
        assert gap >= abs(computed.approach.miss_km - nominal.miss_km)
        assert gap == pytest.approx(measured_km, abs=0.01)

    def test_the_gap_grows_with_the_horizon(self) -> None:
        short = rk45_sgp4_gap_km(GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle, SeparationWindow(_EPOCH, 3600.0))
        long = rk45_sgp4_gap_km(
            GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle, SeparationWindow(_EPOCH, 24 * 3600.0),
        )
        assert short is not None and long is not None
        assert short < long

    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_an_orbit_that_cannot_be_compared_gives_none(self, side: str) -> None:
        red, blue = ("not an element set", _BLUE) if side == "red" else (_RED, "not an element set")
        assert rk45_sgp4_gap_km(red, blue, _SIX_HOURS) is None

    @pytest.mark.parametrize("arc", ["re-enters", "fails"])
    def test_an_arc_that_cannot_be_integrated_gives_none(self, arc: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """An RK45 arc that meets the 100 km floor, or whose solve fails, has no gap to give."""

        def dense_arc(*_: object) -> None:
            if arc == "re-enters":
                raise monte_carlo._ReenteredError("the arc reaches the floor")

        monkeypatch.setattr(monte_carlo, "_dense_arc", dense_arc)
        assert rk45_sgp4_gap_km(_RED, _BLUE, _SIX_HOURS) is None

    @pytest.mark.parametrize("tle", [_RED, _BLUE], ids=["red", "blue"])
    def test_an_sgp4_failure_on_the_grid_gives_none(self, tle: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagator, "TLEOrbit", _failing(tle, after_s=7200.0))
        assert rk45_sgp4_gap_km(_RED, _BLUE, _SIX_HOURS) is None

    def test_the_window_start_is_where_both_arcs_begin(self) -> None:
        later = SeparationWindow(_EPOCH + timedelta(hours=1), 3600.0)
        gap = rk45_sgp4_gap_km(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, later)
        assert gap is not None and gap < 1.0


def _burn(lead_h: float) -> ManoeuvreHypothesis:
    """A plane-change hypothesis burning *lead_h* hours before EPOCH, from red's SGP4 state there, as the panel builds it."""
    at = EPOCH - timedelta(hours=lead_h)
    red = monte_carlo.elset_state(PLANE_CHANGE.red_tle, at)
    assert red is not None
    return ManoeuvreHypothesis(
        epoch_utc=at, delta_v_magnitude_km_s=0.001, delta_v_radial=0.0, delta_v_in_track=0.001,
        delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=red.state_eci_km.copy(),
    )


def _red_from_burn_km(hypothesis: ManoeuvreHypothesis, window: SeparationWindow) -> float:
    """Measured independently: red's unburnt RK45 arc from the burn, at bstar_post, against SGP4 over the window."""
    burn_s = (hypothesis.epoch_utc - window.start_utc).total_seconds()
    state = hypothesis.pre_manoeuvre_state_eci_km
    back = monte_carlo._dense_arc(state, burn_s, min(burn_s, 0.0), hypothesis.bstar_post)
    ahead = monte_carlo._dense_arc(state, burn_s, max(burn_s, window.span_s), hypothesis.bstar_post)
    assert back is not None and ahead is not None
    orbit = TLEOrbit(PLANE_CHANGE.red_tle)
    return max(
        float(np.linalg.norm((back(t) if t < burn_s else ahead(t))[:3]
                             - orbit.propagate(window.start_utc + timedelta(seconds=t)).r))
        for t in np.arange(0.0, window.span_s + 1.0, window.step_s).tolist()
    )


class TestTheGapIsMeasuredOnTheSampledRowsOwnArcs:
    """A sampled row integrates red from its hypothesis's pre-manoeuvre state at the burn, at bstar_post, not
    from the window start: a burn before the window integrates red for longer, and the gap grows with it."""

    @pytest.mark.parametrize(
        ("lead_h", "measured_km"), [(2.0, 0.628), (24.0, 3.615), (72.0, 4.428), (-0.5, 0.288)],
        ids=["2 h before", "24 h before", "72 h before", "inside the window"],
    )
    def test_red_is_measured_from_the_burn(self, lead_h: float, measured_km: float) -> None:
        """Plane change over 1 h: the window-start gap is 0.412 km; from a burn 72 h earlier it is 4.428 km."""
        hypothesis = _burn(lead_h)
        gap = rk45_sgp4_gap_km(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _PC_HOUR, (hypothesis,))
        blue_only = cast("float", rk45_sgp4_gap_km(PLANE_CHANGE.blue_tle, PLANE_CHANGE.blue_tle, _PC_HOUR)) / 2.0
        assert gap == pytest.approx(_red_from_burn_km(hypothesis, _PC_HOUR) + blue_only, abs=1e-6)
        assert gap == pytest.approx(measured_km, abs=0.01)

    def test_the_largest_red_gap_of_the_sampled_rows_is_taken(self) -> None:
        both = rk45_sgp4_gap_km(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _PC_HOUR, (_burn(72.0), _burn(2.0)))
        assert both == rk45_sgp4_gap_km(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _PC_HOUR, (_burn(72.0),))

    def test_a_sampled_rows_arc_that_cannot_be_integrated_gives_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(monte_carlo, "_unburnt_arc", lambda *_: None)
        assert rk45_sgp4_gap_km(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _PC_HOUR, (_burn(2.0),)) is None
