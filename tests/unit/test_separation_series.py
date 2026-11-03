"""A separation series from the Monte Carlo engine against a blue track (SPC-110).

monte_carlo.py's run_monte_carlo returns element statistics at the horizon,
not trajectories, so a closest approach cannot come from it. The separation
series propagates each sample's red arc and the blue asset with the same
RK45, J2 and drag model, and finds each sample's closest approach with the
shared helper, spectre/astro/closest_approach.py.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro import monte_carlo
from spectre.astro.closest_approach import MAX_SAMPLES
from spectre.astro.constants import R_EARTH
from spectre.astro.monte_carlo import (
    CONVERGENCE_TOLERANCE_KM,
    REENTRY_FLOOR_KM,
    BlueTrack,
    ManoeuvreHypothesis,
    SeparationSeries,
    SeparationWindow,
    elset_state,
    generate_samples,
    miss_tolerance_km,
    percentile_half_width_km,
    propagate_single_sample,
    run_separation_series,
    separation_integration_s,
)
from spectre.astro.propagator import TLEOrbit
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit.test_astro import ISS_TLE

#: B* as ISS_TLE writes it in columns 54 to 61: 30143-3.
_ISS_BSTAR = 0.30143e-3
_ISS_AT = datetime(2024, 2, 14, 12, 0, tzinfo=UTC)


def test_an_element_set_states_its_drag_term() -> None:
    assert TLEOrbit(ISS_TLE).bstar == _ISS_BSTAR


def test_a_zero_drag_term_reads_zero() -> None:
    assert TLEOrbit(PLANE_CHANGE.blue_tle).bstar == 0.0


def test_an_element_set_gives_its_teme_state_and_drag_term() -> None:
    track = elset_state(ISS_TLE, _ISS_AT)
    expected = TLEOrbit(ISS_TLE).propagate(_ISS_AT)
    assert isinstance(track, BlueTrack)
    assert np.array_equal(track.state_eci_km, np.concatenate([expected.r, expected.v]))
    assert track.bstar == _ISS_BSTAR
    assert track.epoch_utc == _ISS_AT


@pytest.mark.parametrize(
    "tle",
    [
        "not an element set",
        "1 25544U 98067A   24045.51891898  .00016717  00000-0  30143-3 0  9993\n2 25544  garbage",
    ],
    ids=["one-line", "unparsable-line-2"],
)
def test_a_bad_element_set_gives_no_state(tle: str) -> None:
    assert elset_state(tle, _ISS_AT) is None


def test_an_element_set_that_cannot_reach_the_time_gives_no_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def sgp4_error(self: TLEOrbit, epoch: datetime) -> None:
        raise RuntimeError(f"SGP4 error code 6 at {epoch}")

    monkeypatch.setattr(TLEOrbit, "propagate", sgp4_error)
    assert elset_state(ISS_TLE, _ISS_AT) is None


# The series itself, on the plane-change reference case: blue and red on
# crossing planes, closest 10.4 km apart about 1,411 s after EPOCH, inside a
# 1 h window.

_WINDOW = SeparationWindow(start_utc=EPOCH, span_s=PLANE_CHANGE.horizon_s, step_s=PLANE_CHANGE.step_s)
_SEED = 7
#: Dispersions for a series whose misses spread (km/s, degrees, seconds, B*).
_DISPERSED: dict[str, Any] = {
    "delta_v_magnitude_1sigma_km_s": 0.0003,
    "delta_v_pointing_1sigma_deg": 5.0,
    "epoch_1sigma_seconds": 30.0,
    "bstar_1sigma": 1e-5,
}


def _state(tle: str, at: datetime) -> BlueTrack:
    track = elset_state(tle, at)
    assert track is not None
    return track


_BLUE = _state(PLANE_CHANGE.blue_tle, EPOCH)


def _hypothesis(**changes: Any) -> ManoeuvreHypothesis:
    """A 1 m/s in-track burn by red, from red's state at the burn, no spread, then *changes*."""
    burn_at = changes.get("epoch_utc", EPOCH)
    base = ManoeuvreHypothesis(
        epoch_utc=burn_at,
        delta_v_magnitude_km_s=0.001,
        delta_v_radial=0.0, delta_v_in_track=0.001, delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=_state(PLANE_CHANGE.red_tle, burn_at).state_eci_km,
        delta_v_magnitude_1sigma_km_s=0.0,
        delta_v_pointing_1sigma_deg=0.0,
        epoch_1sigma_seconds=0.0,
        bstar_post=0.0,
        bstar_1sigma=0.0,
        n_samples=50,
        random_seed=_SEED,
    )
    return replace(base, **changes)


def _misses(series: SeparationSeries) -> list[float]:
    return [a.miss_km for a in series.approaches]


@pytest.fixture(scope="module")
def dispersed() -> SeparationSeries:
    return run_separation_series(_hypothesis(**_DISPERSED), _BLUE, _WINDOW)


def test_with_no_spread_every_sample_gives_one_value() -> None:
    series = run_separation_series(_hypothesis(), _BLUE, _WINDOW)
    assert series.n_samples_run == 50
    assert series.n_failed == 0
    assert len(series.approaches) == 50
    assert len(set(_misses(series))) == 1
    assert series.miss_km_p5 == series.miss_km_p50 == series.miss_km_p95
    # numpy's mean of 50 equal values can differ from them in the last place.
    assert series.miss_km_std == pytest.approx(0.0, abs=1e-12)
    assert series.percentile_half_width_km == 0.0
    assert series.converged is True
    # Every miss equals P5, so every sample is at or below it.
    assert series.earliest_tca_at_or_below_p5_s == series.approaches[0].tca_s
    assert series.n_reentered == 0


def test_the_percentiles_are_numpys_over_the_sample_misses(dispersed: SeparationSeries) -> None:
    misses = _misses(dispersed)
    assert len(misses) == 50
    assert max(misses) - min(misses) > 0.1, "the dispersions must spread the misses for this test to mean anything"
    p5, p50, p95 = (float(p) for p in np.percentile(misses, [5, 50, 95]))
    assert (dispersed.miss_km_p5, dispersed.miss_km_p50, dispersed.miss_km_p95) == (p5, p50, p95)
    assert dispersed.percentiles == {5: p5, 50: p50, 95: p95}
    assert dispersed.miss_km_std == float(np.std(misses))
    assert dispersed.closest_sample_km == min(misses)


def test_the_earliest_tca_is_taken_from_the_samples_at_or_below_p5(dispersed: SeparationSeries) -> None:
    at_or_below = [a.tca_s for a in dispersed.approaches if a.miss_km <= dispersed.miss_km_p5]
    assert len(at_or_below) == 3, "P5 of 50 lies between the 3rd and 4th smallest misses"
    assert dispersed.earliest_tca_at_or_below_p5_s == min(at_or_below)


def test_convergence_is_the_engines_own_check(dispersed: SeparationSeries) -> None:
    half_width = percentile_half_width_km(_misses(dispersed), seed=_SEED)
    assert math.isfinite(half_width)
    assert dispersed.percentile_half_width_km == half_width
    assert dispersed.tolerance_km == miss_tolerance_km(dispersed.miss_km_p5)
    assert dispersed.converged is (half_width <= dispersed.tolerance_km)


def test_a_half_width_exactly_at_the_relative_tolerance_has_converged(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPC-117: at a P5 over 20 km the tolerance is 5 % of it; a half-width just over that has not converged."""
    monkeypatch.setattr(monte_carlo, "miss_tolerance_km", lambda p5: 0.05 * 400.0 if math.isfinite(p5) else 1.0)
    for half_width, converged in ((20.0, True), (math.nextafter(20.0, math.inf), False)):
        monkeypatch.setattr(monte_carlo, "percentile_half_width_km", lambda *_, hw=half_width, **__: hw)
        series = run_separation_series(_hypothesis(n_samples=1), _BLUE, _WINDOW)
        assert series.tolerance_km == 20.0
        assert series.converged is converged


def test_a_half_width_exactly_at_the_tolerance_has_converged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monte_carlo, "percentile_half_width_km", lambda *_, **__: CONVERGENCE_TOLERANCE_KM)
    series = run_separation_series(_hypothesis(n_samples=1), _BLUE, _WINDOW)
    assert series.percentile_half_width_km == CONVERGENCE_TOLERANCE_KM
    assert series.converged is True


def test_below_50_samples_the_series_has_not_converged() -> None:
    series = run_separation_series(_hypothesis(n_samples=49), _BLUE, _WINDOW)
    assert len(series.approaches) == 49
    assert series.percentile_half_width_km == math.inf
    assert series.converged is False


def test_a_burn_after_the_window_gives_the_unburnt_approach() -> None:
    after = EPOCH + timedelta(seconds=_WINDOW.span_s + 600.0)
    burnt = run_separation_series(
        _hypothesis(epoch_utc=after, n_samples=3, delta_v_magnitude_km_s=0.05), _BLUE, _WINDOW,
    )
    unburnt = run_separation_series(
        _hypothesis(epoch_utc=after, n_samples=3, delta_v_magnitude_km_s=0.0), _BLUE, _WINDOW,
    )
    assert burnt.n_failed == 0
    assert len(burnt.approaches) == 3
    assert burnt.approaches == unburnt.approaches
    assert abs(burnt.miss_km_p50 - PLANE_CHANGE.miss_km) < 1.0


def test_a_burn_before_the_window_is_applied() -> None:
    before = EPOCH - timedelta(hours=1)
    burnt = run_separation_series(_hypothesis(epoch_utc=before, n_samples=1), _BLUE, _WINDOW)
    unburnt = run_separation_series(
        _hypothesis(epoch_utc=before, n_samples=1, delta_v_magnitude_km_s=0.0), _BLUE, _WINDOW,
    )
    assert burnt.n_failed == unburnt.n_failed == 0
    assert abs(burnt.miss_km_p50 - unburnt.miss_km_p50) > 1.0, (burnt.miss_km_p50, unburnt.miss_km_p50)


def test_a_timing_offset_moves_the_burn() -> None:
    # A 20 m/s radial burn 20 minutes before the crossing: when it fires sets where red crosses.
    changes: dict[str, Any] = {
        "epoch_utc": EPOCH + timedelta(seconds=180.0), "n_samples": 5,
        "delta_v_magnitude_km_s": 0.02, "delta_v_radial": 0.02, "delta_v_in_track": 0.0,
    }
    fixed = run_separation_series(_hypothesis(**changes), _BLUE, _WINDOW)
    moved = run_separation_series(_hypothesis(epoch_1sigma_seconds=120.0, **changes), _BLUE, _WINDOW)
    fixed_tcas = [a.tca_s for a in fixed.approaches]
    moved_tcas = [a.tca_s for a in moved.approaches]
    assert len(set(fixed_tcas)) == 1
    assert max(moved_tcas) - min(moved_tcas) > 1.0, moved_tcas


@pytest.mark.parametrize("failure", ["raises", "does-not-succeed"])
def test_a_failed_sample_is_counted(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    hypothesis = _hypothesis(n_samples=5, epoch_1sigma_seconds=30.0)
    burn_times = generate_samples(hypothesis)[:, 3]
    real = monte_carlo._dense_arc

    def fail_the_third(state: np.ndarray, t0_s: float, t1_s: float, bstar: float) -> Any:
        if t0_s == burn_times[2]:
            if failure == "raises":
                raise ArithmeticError("overflow in the third sample")
            return None
        return real(state, t0_s, t1_s, bstar)

    monkeypatch.setattr(monte_carlo, "_dense_arc", fail_the_third)
    series = run_separation_series(hypothesis, _BLUE, _WINDOW)
    assert series.n_failed == 1
    assert len(series.approaches) == 4
    assert series.n_samples_run == 5


def _overflow(*_: Any) -> None:
    raise FloatingPointError("overflow in the shared arcs")


@pytest.mark.parametrize("arc", [lambda *_: None, _overflow], ids=["does-not-succeed", "raises"])
def test_with_every_sample_failed_the_statistics_are_not_numbers(
    monkeypatch: pytest.MonkeyPatch, arc: Callable[..., None],
) -> None:
    monkeypatch.setattr(monte_carlo, "_dense_arc", arc)
    series = run_separation_series(_hypothesis(n_samples=4), _BLUE, _WINDOW)
    assert series.n_failed == 4
    assert series.approaches == ()
    assert all(math.isnan(v) for v in (*series.percentiles.values(), series.miss_km_std))
    assert math.isnan(series.closest_sample_km)
    assert math.isnan(series.earliest_tca_at_or_below_p5_s)
    assert series.n_at_window_edge == 0
    assert series.converged is False


def test_the_same_seed_gives_the_same_series() -> None:
    hypothesis = _hypothesis(n_samples=5, **_DISPERSED)
    first = run_separation_series(hypothesis, _BLUE, _WINDOW)
    second = run_separation_series(hypothesis, _BLUE, _WINDOW)
    assert first.approaches == second.approaches
    assert first.percentiles == second.percentiles
    assert first.random_seed == second.random_seed == _SEED


def test_samples_still_closing_at_the_window_end_are_counted() -> None:
    short = SeparationWindow(start_utc=EPOCH, span_s=1200.0, step_s=60.0)
    series = run_separation_series(_hypothesis(n_samples=3), _BLUE, short)
    assert series.n_at_window_edge == 3
    assert all(a.tca_s == short.span_s for a in series.approaches)


def test_the_series_names_its_propagator_and_window() -> None:
    series = run_separation_series(_hypothesis(n_samples=1), _BLUE, _WINDOW)
    assert series.propagator == "RK45 with J2 and exponential drag, red and blue alike"
    assert series.window == _WINDOW
    assert _WINDOW.step_s == SeparationWindow(start_utc=EPOCH, span_s=1.0).step_s == 60.0


@pytest.mark.parametrize(
    "window",
    [
        SeparationWindow(start_utc=EPOCH, span_s=60.0 * MAX_SAMPLES, step_s=60.0),
        SeparationWindow(start_utc=EPOCH, span_s=3600.0, step_s=0.0),
        SeparationWindow(start_utc=EPOCH, span_s=-3600.0, step_s=60.0),
        SeparationWindow(start_utc=EPOCH, span_s=math.nan, step_s=60.0),
    ],
    ids=["over-the-sample-limit", "zero-step", "negative-span", "nan-span"],
)
def test_a_window_the_helper_cannot_take_is_refused_before_any_integration(
    monkeypatch: pytest.MonkeyPatch, window: SeparationWindow,
) -> None:
    def no_integration(*_: Any, **__: Any) -> None:
        pytest.fail("the window must be refused before anything is integrated")

    monkeypatch.setattr(monte_carlo, "solve_ivp", no_integration)
    with pytest.raises(ValueError, match="window"):
        run_separation_series(_hypothesis(n_samples=1), _BLUE, window)


def test_blue_must_hold_at_the_window_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_integration(*_: Any, **__: Any) -> None:
        pytest.fail("a blue track from another instant must be refused before anything is integrated")

    early = _state(PLANE_CHANGE.blue_tle, EPOCH - timedelta(minutes=10))
    monkeypatch.setattr(monte_carlo, "solve_ivp", no_integration)
    with pytest.raises(ValueError, match="blue"):
        run_separation_series(_hypothesis(n_samples=1), early, _WINDOW)


# Each sample checked against an independent propagation: red burnt and
# propagated by the horizon engine's own per-sample path (propagate_single_sample,
# which integrates from the nominal burn to the burn and on to the asked
# instant), blue integrated from the window start, and their separation taken
# at the series' TCA. The series must match it sample by sample.


def _independent_miss_km(
    hypothesis: ManoeuvreHypothesis, sample: np.ndarray, blue: BlueTrack, window: SeparationWindow, tca_s: float,
) -> float:
    """Red's and blue's separation at *tca_s*, propagated without the series' arcs."""
    pre = hypothesis.pre_manoeuvre_state_eci_km
    to_tca_s = tca_s - (hypothesis.epoch_utc - window.start_utc).total_seconds()
    burnt = propagate_single_sample(sample, pre, hypothesis.bstar_post, to_tca_s / 3600.0)
    if burnt is None:   # the sample burns after the TCA: red is still unburnt there
        unburnt = monte_carlo._integrate(pre, to_tca_s, hypothesis.bstar_post)
        assert unburnt is not None
        red = unburnt[:3]
    else:
        red = np.array(burnt["r_final"])
    blue_at = monte_carlo._integrate(blue.state_eci_km, tca_s, blue.bstar)
    assert blue_at is not None
    return float(np.linalg.norm(red - blue_at[:3]))


def _assert_matches_independent_propagation(
    hypothesis: ManoeuvreHypothesis, blue: BlueTrack, window: SeparationWindow, series: SeparationSeries,
    tolerance_km: float,
) -> None:
    samples = generate_samples(hypothesis)
    assert series.n_failed == 0
    gaps = [
        abs(_independent_miss_km(hypothesis, sample, blue, window, a.tca_s) - a.miss_km)
        for sample, a in zip(samples, series.approaches, strict=True)
    ]
    assert max(gaps) < tolerance_km, gaps


def test_each_dispersed_sample_matches_an_independent_propagation(dispersed: SeparationSeries) -> None:
    hypothesis = _hypothesis(**_DISPERSED)
    offsets = generate_samples(hypothesis)[:, 3]
    assert (offsets < 0.0).sum() >= 10, "some samples must burn before the window start for this test to mean anything"
    # Measured agreement 2.2e-5 km; the dense arcs and end-point solves differ only in step choice.
    _assert_matches_independent_propagation(hypothesis, _BLUE, _WINDOW, dispersed, tolerance_km=1e-4)


@pytest.mark.parametrize(
    "ric", [(0.001, 0.0, 0.0), (0.0, 0.001, 0.0), (0.0, 0.0, 0.001)], ids=["radial", "in-track", "cross-track"],
)
def test_a_burn_along_each_ric_axis_matches_an_independent_propagation(ric: tuple[float, float, float]) -> None:
    radial, in_track, cross_track = ric
    hypothesis = _hypothesis(
        epoch_utc=EPOCH - timedelta(minutes=10), n_samples=1,
        delta_v_radial=radial, delta_v_in_track=in_track, delta_v_cross_track=cross_track,
    )
    series = run_separation_series(hypothesis, _BLUE, _WINDOW)
    _assert_matches_independent_propagation(hypothesis, _BLUE, _WINDOW, series, tolerance_km=1e-4)


#: Drag strong enough to see: B* 0.015 is the most the ballistic floor takes.
_HEAVY_BSTAR = 0.015
_DRAG_START = EPOCH - timedelta(hours=3)
_DRAG_WINDOW = SeparationWindow(start_utc=_DRAG_START, span_s=4 * 3600.0, step_s=60.0)


def test_drag_on_red_and_blue_matches_an_independent_propagation() -> None:
    blue = _state(PLANE_CHANGE.blue_tle, _DRAG_START)._replace(bstar=_HEAVY_BSTAR)
    hypothesis = _hypothesis(
        epoch_utc=_DRAG_START - timedelta(hours=1), n_samples=10,
        bstar_post=_HEAVY_BSTAR, **{**_DISPERSED, "bstar_1sigma": _HEAVY_BSTAR / 4},
    )
    series = run_separation_series(hypothesis, blue, _DRAG_WINDOW)
    without_blue_drag = run_separation_series(hypothesis, blue._replace(bstar=0.0), _DRAG_WINDOW)
    shift = max(abs(a.miss_km - b.miss_km) for a, b in zip(series.approaches, without_blue_drag.approaches, strict=True))
    assert shift > 2e-4, "blue's drag must move the misses by more than the tolerance for this test to mean anything"
    # Measured agreement 2.2e-6 km.
    _assert_matches_independent_propagation(hypothesis, blue, _DRAG_WINDOW, series, tolerance_km=2e-5)


# Re-entry: below REENTRY_FLOOR_KM a sample has no closest approach to give.


def test_the_floor_is_the_conventional_edge_of_space() -> None:
    assert REENTRY_FLOOR_KM == 100.0


def test_a_sample_that_drops_below_the_floor_is_counted_re_entered() -> None:
    # A 400 m/s retrograde burn takes red from 550 km into the atmosphere inside the hour.
    hypothesis = _hypothesis(
        n_samples=2, delta_v_magnitude_km_s=0.4, delta_v_in_track=-0.4, bstar_post=1e-4,
    )
    series = run_separation_series(hypothesis, _BLUE, _WINDOW)
    assert series.approaches == ()
    assert series.n_failed == 2
    assert series.n_reentered == 2
    assert math.isnan(series.miss_km_p50)


def _below_the_floor(at: datetime) -> BlueTrack:
    """A state 90 km up, at circular speed."""
    radius = R_EARTH + 90.0
    return BlueTrack(np.array([radius, 0.0, 0.0, 0.0, math.sqrt(398600.4418 / radius), 0.0]), 1e-4, at)


def test_blue_below_the_floor_fails_every_sample_without_calling_red_re_entered() -> None:
    series = run_separation_series(_hypothesis(n_samples=3), _below_the_floor(EPOCH), _WINDOW)
    assert series.approaches == ()
    assert series.n_failed == 3
    assert series.n_reentered == 0


def test_red_below_the_floor_before_its_burn_fails_every_sample() -> None:
    hypothesis = _hypothesis(n_samples=3, pre_manoeuvre_state_eci_km=_below_the_floor(EPOCH).state_eci_km)
    series = run_separation_series(hypothesis, _BLUE, _WINDOW)
    assert series.approaches == ()
    assert series.n_failed == 3
    assert series.n_reentered == 0


# Cost: a series integrates blue over the window, red's unburnt arc once, and
# each sample from its burn to the window end, so a burn long before the
# window costs as much as a longer window.


def test_a_burn_at_the_window_start_integrates_the_window_once_per_arc() -> None:
    hypothesis = _hypothesis(n_samples=3)
    # Blue 3,600 s, red unburnt 3,600 s, and 3 samples of 3,600 s.
    assert separation_integration_s(hypothesis, _WINDOW) == 5 * 3600.0
    assert run_separation_series(hypothesis, _BLUE, _WINDOW).integration_s == 5 * 3600.0


def test_a_burn_a_day_before_the_window_counts_the_look_back() -> None:
    hypothesis = _hypothesis(epoch_utc=EPOCH - timedelta(hours=24), n_samples=3)
    # Blue 3,600 s, red unburnt 25 h, and 3 samples of 25 h each.
    assert separation_integration_s(hypothesis, _WINDOW) == 3600.0 + 4 * 25 * 3600.0


def test_a_burn_after_the_window_integrates_no_sample() -> None:
    hypothesis = _hypothesis(epoch_utc=EPOCH + timedelta(seconds=_WINDOW.span_s + 600.0), n_samples=3)
    # Blue 3,600 s and red unburnt from the window start to the burn, 4,200 s.
    assert separation_integration_s(hypothesis, _WINDOW) == 3600.0 + 4200.0


def test_the_look_back_follows_the_earliest_sample_burn() -> None:
    hypothesis = _hypothesis(n_samples=4, epoch_1sigma_seconds=60.0)
    burns = generate_samples(hypothesis)[:, 3]
    earliest = min(0.0, float(burns.min()))
    expected = 3600.0 + (3600.0 - earliest) + sum(3600.0 - b for b in burns)
    assert separation_integration_s(hypothesis, _WINDOW) == pytest.approx(expected, rel=1e-12)


# The tick (SPC-113): the decision layer's budget and stop are checked once per sample, outside the sample's
# own excepts, so a tick that raises stops the series and reaches the caller.


def test_the_tick_is_called_once_per_sample_with_its_count() -> None:
    """B9."""
    ticks: list[tuple[int, int]] = []
    series = run_separation_series(_hypothesis(n_samples=5), _BLUE, _WINDOW, tick=lambda k, n: ticks.append((k, n)))
    assert ticks == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    assert len(series.approaches) == 5


def test_the_tick_follows_its_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tick k comes after sample k has run, so a budget reading it counts k samples finished, not k - 1."""
    tried: list[int] = []
    real = monte_carlo._try_sample

    def counted(*args: Any, **kwargs: Any) -> Any:
        tried.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(monte_carlo, "_try_sample", counted)
    seen: list[tuple[int, int]] = []
    run_separation_series(_hypothesis(n_samples=4), _BLUE, _WINDOW, tick=lambda k, _n: seen.append((k, len(tried))))
    assert seen == [(1, 1), (2, 2), (3, 3), (4, 4)]


class _StopHereError(Exception):
    """What the test's tick raises."""


def test_a_tick_that_raises_stops_the_series_and_reaches_the_caller() -> None:
    """B9: the ValueError and ArithmeticError excepts around each sample do not swallow it, and no result returns."""
    ticks: list[int] = []

    def tick(k: int, _n: int) -> None:
        ticks.append(k)
        if k == 2:
            raise _StopHereError

    with pytest.raises(_StopHereError):
        run_separation_series(_hypothesis(n_samples=5), _BLUE, _WINDOW, tick=tick)
    assert ticks == [1, 2]


def test_a_tick_that_raises_a_value_error_is_not_counted_as_a_failed_sample() -> None:
    """The tick runs outside _try_sample, so even an exception its excepts name propagates."""

    def tick(_k: int, _n: int) -> None:
        raise ValueError("stop")

    with pytest.raises(ValueError, match="stop"):
        run_separation_series(_hypothesis(n_samples=3), _BLUE, _WINDOW, tick=tick)
