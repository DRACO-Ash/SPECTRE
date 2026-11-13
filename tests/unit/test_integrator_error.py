"""The production RK45's own error, measured here and stated in the sampled basis note (SPC-214, evaluation F-27).

The lead ruled that the tolerances stay at RK45_RTOL 1e-8 and RK45_ATOL 1e-10, since tightening them would move
stored figures and runtime, and that the error is stated instead. This measures it: each object of three reference
pairs (tests/unit/_decision_reference.py, through SPECTRE's SGP4 at the cases' epoch, B* 1e-4 so drag is on) is
integrated by the engine's RK45 on both its paths, the Monte Carlo sample's (monte_carlo._integrate) and the dense
arc every separation series searches (monte_carlo.rk45_arc), and by DOP853 at rtol 1e-12 and atol 1e-14 over the same
equations as the reference. Position error is read every 60 s to 24, 48 and 72 h, and so is the error in the pair's
separation, which is what a closest approach reads.

Measured at this commit (scipy 1.17.1), the largest up to each horizon:

● position, LEO: 0.092 km by 24 h, 0.386 km by 48 h, 0.881 km by 72 h (the 550 km, 97.4 degree pair; the 500 km pair
  0.068, 0.285 and 0.653 km);
● position, GEO: 0.0029 km by 24 h, 0.0043 km by 48 h, 0.0148 km by 72 h;
● separation: 0.0118 km by 24 h, 0.108 km by 48 h, 0.379 km by 72 h (the 500 km co-planar pair; GEO under 0.001 km).

The evaluation's probe P-13 reported 0.285 km at 48 h and 0.652 km at 72 h in LEO and up to 0.353 km of separation
error; this measurement agrees on position for the same 500 km orbit, finds 0.379 km of separation error at 72 h on
its pair, and 0.881 km of position error on the 550 km polar orbit P-13 did not report.

monte_carlo.INTEGRATOR_ERROR_KM states each, rounded up; this holds each stated figure at or above what is measured,
and no more than 0.01 km above it, so a looser integrator fails here and so does a stated figure left behind.
"""

from __future__ import annotations

import dataclasses
import functools
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo
from spectre.astro.monte_carlo import SeparationWindow
from spectre.domain import decision
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE, ReferenceCase
from tests.unit.test_p5_half_width import _SKEWED, _series

_HOUR_S = 3600.0
_BSTAR = 1e-4
_STEP_S = 60.0
_HORIZONS = (24, 48, 72)
#: Each stated figure is at most this much above the one measured, km.
_SLACK_KM = 0.01
_PAIRS: dict[str, tuple[str, ReferenceCase]] = {
    "500 km LEO": ("LEO", COPLANAR_LEO), "550 km polar LEO": ("LEO", PLANE_CHANGE), "GEO": ("GEO", GEO_DRIFT_IN),
}


def _start(tle: str) -> np.ndarray:
    track = monte_carlo.elset_state(tle, EPOCH)
    assert track is not None
    return track.state_eci_km


def _reference(state: np.ndarray, span_s: float) -> object:
    sol = solve_ivp(monte_carlo._j2_drag_ode, (0.0, span_s), state, method="DOP853", rtol=1e-12, atol=1e-14,
                    args=(monte_carlo._ballistic_coefficient_kg_m2(_BSTAR),), dense_output=True)
    assert sol.success
    return sol.sol


@functools.cache
def _measured(pair: str) -> dict[int, tuple[float, float]]:
    """By each horizon, the largest position error of either object and the largest separation error, km."""
    _, case = _PAIRS[pair]
    span = max(_HORIZONS) * _HOUR_S
    states = [_start(case.red_tle), _start(case.blue_tle)]
    refs = [_reference(s, span) for s in states]
    dense = [monte_carlo.rk45_arc(s, span, _BSTAR) for s in states]
    assert None not in dense
    grid = np.arange(0.0, span + 1.0, _STEP_S)
    prod = np.array([[arc(t)[:3] for t in grid] for arc in dense])     # type: ignore[misc]
    ref = np.array([[sol(t)[:3] for t in grid] for sol in refs])       # type: ignore[operator]
    position = np.max(np.linalg.norm(prod - ref, axis=2), axis=0)
    separation = np.linalg.norm((prod[0] - prod[1]) - (ref[0] - ref[1]), axis=1)
    out = {}
    for hours in _HORIZONS:
        upto = grid <= hours * _HOUR_S
        # The Monte Carlo sample's path ends at the horizon itself: its error there is held to the same figure.
        ends = [monte_carlo._integrate(s, hours * _HOUR_S, _BSTAR) for s in states]
        at_end = max(float(np.linalg.norm(e[:3] - r(hours * _HOUR_S)[:3]))     # type: ignore[index, operator]
                     for e, r in zip(ends, refs, strict=True))
        out[hours] = (max(float(np.max(position[upto])), at_end), float(np.max(separation[upto])))
    return out


def test_the_tolerances_are_the_production_ones() -> None:
    assert (monte_carlo.RK45_RTOL, monte_carlo.RK45_ATOL) == (1e-8, 1e-10)


@pytest.mark.parametrize("hours", _HORIZONS)
def test_each_stated_position_error_holds_and_is_tight(hours: int) -> None:
    stated_leo, stated_geo, _ = monte_carlo.INTEGRATOR_ERROR_KM[hours]
    leo = max(_measured(p)[hours][0] for p, (regime, _) in _PAIRS.items() if regime == "LEO")
    geo = _measured("GEO")[hours][0]
    assert leo <= stated_leo <= leo + _SLACK_KM, f"LEO by {hours} h: measured {leo:.4f} km"
    assert geo <= stated_geo <= geo + _SLACK_KM, f"GEO by {hours} h: measured {geo:.4f} km"


@pytest.mark.parametrize("hours", _HORIZONS)
def test_each_stated_separation_error_holds_and_is_tight(hours: int) -> None:
    stated = monte_carlo.INTEGRATOR_ERROR_KM[hours][2]
    worst = max(_measured(p)[hours][1] for p in _PAIRS)
    assert worst <= stated <= worst + _SLACK_KM, f"by {hours} h: measured {worst:.4f} km"


def test_the_error_grows_with_the_horizon() -> None:
    rows = [monte_carlo.INTEGRATOR_ERROR_KM[h] for h in _HORIZONS]
    for column in range(3):
        assert [row[column] for row in rows] == sorted(row[column] for row in rows)
    assert _measured("500 km LEO")[72][0] > 0.6, "the 500 km LEO orbit, as probe P-13 measured it"


class TestTheWords:
    def test_a_horizon_takes_the_shortest_measured_one_at_or_past_it(self) -> None:
        words = monte_carlo.integrator_error_words(30.0)
        assert words == (
            "integrator error, not in the spread: RK45 at rtol 1e-08 and atol 1e-10, against DOP853 at rtol 1e-12 on "
            "three reference pairs, put each object within 0.39 km of the reference in LEO and 0.005 km at GEO by 48 "
            "h, and the pair's separation within 0.11 km; between two unlike orbits the separation error can reach "
            "both objects' errors added"
        )
        assert monte_carlo.integrator_error_words(24.0).endswith("0.003 km at GEO by 24 h, and the pair's "
                                                                 "separation within 0.02 km; between two unlike "
                                                                 "orbits the separation error can reach both "
                                                                 "objects' errors added")

    def test_a_horizon_past_the_longest_measured_says_so(self) -> None:
        words = monte_carlo.integrator_error_words(96.0)
        assert "0.89 km of the reference in LEO and 0.015 km at GEO by 72 h" in words
        assert words.endswith("; it was measured to 72 h only, and grows with time")

    def test_the_sampled_note_ends_with_it(self) -> None:
        note = decision._sampled_bases(_series(_SKEWED), 12.0).closest_approach_km.note
        assert note.endswith("; " + monte_carlo.integrator_error_words(12.0))
        assert "by 24 h" in note


class TestTheSpanIsWhatRK45Runs:
    """V0.40 review: the words were keyed to the horizon, but each sample's red arc runs from its burn, which can be
    days before the window; a 72 h window with the burn 48 h before it integrates 120 h."""

    def _window(self, hours: float) -> SeparationWindow:
        return SeparationWindow(start_utc=datetime(2026, 10, 17, 12, tzinfo=UTC), span_s=hours * 3600.0)

    def test_a_burn_48_h_before_a_72_h_window_integrates_120_h_and_is_past_what_was_measured(self) -> None:
        window = self._window(72.0)
        burn = window.start_utc - timedelta(hours=48.0)
        assert decision._integrated_hours(window, burn) == pytest.approx(120.0)
        series = dataclasses.replace(_series(_SKEWED), window=window)
        note = decision._sampled_bases(series, 72.0, burn_at=burn).closest_approach_km.note
        assert note.endswith("RK45 runs up to 120.0 h here, from the burn to the window's end; "
                             + monte_carlo.integrator_error_words(120.0))
        assert note.endswith("; it was measured to 72 h only, and grows with time")

    def test_a_burn_inside_the_window_integrates_the_window(self) -> None:
        window = self._window(30.0)
        burn = window.start_utc + timedelta(hours=2.0)
        assert decision._integrated_hours(window, burn) == pytest.approx(30.0)
        assert decision._integrated_hours(window, None) == pytest.approx(30.0)
        note = decision._sampled_bases(dataclasses.replace(_series(_SKEWED), window=window), 30.0,
                                       burn_at=burn).closest_approach_km.note
        assert "RK45 runs up to 30.0 h here, from the window's start to its end; " in note
        assert "by 48 h" in note and "measured to 72 h only" not in note
