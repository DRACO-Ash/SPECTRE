"""A transfer's burns flown by the propagator, checked against an independent propagation (SPC-184).

A Hohmann pair from 1,000 to 1,200 km, above the drag ceiling, is propagated here by a separate two-body and J2
integrator (DOP853), each burn applied in the radial, in-track and cross-track frame of the state then. The engine's
nominal arc, its sampled series with no spread, and the arc our burn is sized against must all fly both burns from
the first, as that propagation does. Each later burn's own draws (its timing, its B* and its sample's own draw) and
the stated B* after it are checked to reach the arc, and the burns a sample makes are in time order, none before
the first.

Nothing here reads the wall clock or reaches the network.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.monte_carlo import (
    BlueTrack,
    ManoeuvreHypothesis,
    RedBurn,
    SeparationWindow,
    _chained_red,
    _unburnt_arc,
    nominal_red_arc,
    run_separation_series,
)
from spectre.astro.response_burn import BurnAxis, BurnRequest, hypothesis_response_plan

_START = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_R1, _R2 = R_EARTH + 1000.0, R_EARTH + 1200.0
_DV1 = math.sqrt(MU_EARTH / _R1) * (math.sqrt(2 * _R2 / (_R1 + _R2)) - 1)
_DV2 = math.sqrt(MU_EARTH / _R2) * (1 - math.sqrt(2 * _R1 / (_R1 + _R2)))
_TRANSFER_S = math.pi * math.sqrt(((_R1 + _R2) / 2) ** 3 / MU_EARTH)
_BURN_1_S = 600.0
_BURN_2_S = _BURN_1_S + _TRANSFER_S
_SPAN_S = 3 * 3600.0
_STILL = {"delta_v_magnitude_1sigma_km_s": 0.0, "delta_v_pointing_1sigma_deg": 0.0, "epoch_1sigma_seconds": 0.0,
          "bstar_post": 0.0, "bstar_1sigma": 0.0, "n_samples": 20, "random_seed": 7}


# ── The independent propagation ──

def _ode(_t: float, s: np.ndarray) -> np.ndarray:
    r = s[:3]
    rn = float(np.linalg.norm(r))
    zr2 = (r[2] / rn) ** 2
    j2 = -1.5 * J2_EARTH * MU_EARTH * R_EARTH**2 / rn**5
    a = -MU_EARTH / rn**3 * r + j2 * np.array([r[0] * (1 - 5 * zr2), r[1] * (1 - 5 * zr2), r[2] * (3 - 5 * zr2)])
    return np.concatenate([s[3:], a])


def _leg(state: np.ndarray, t0: float, t1: float) -> Any:
    return solve_ivp(_ode, (t0, t1), state, method="DOP853", rtol=1e-12, atol=1e-12, dense_output=True).sol


def _in_track(state: np.ndarray, dv: float) -> np.ndarray:
    """*state* with *dv*, km/s, added along its own in-track axis: the radial frame's cross-track cross radial."""
    r, v = state[:3], state[3:]
    radial = r / np.linalg.norm(r)
    cross = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
    return np.concatenate([r, v + dv * np.cross(cross, radial)])


def _circular(radius: float, u_deg: float) -> np.ndarray:
    """A circular orbit at *radius*, inclination 51.6 deg, RAAN 40 deg, at argument of latitude *u_deg*."""
    i, node_deg, u = (math.radians(x) for x in (51.6, 40.0, u_deg))
    node = np.array([math.cos(node_deg), math.sin(node_deg), 0.0])
    normal = np.array([math.sin(node_deg) * math.sin(i), -math.cos(node_deg) * math.sin(i), math.cos(i)])
    ahead = np.cross(normal, node)
    speed = math.sqrt(MU_EARTH / radius)
    return np.concatenate([radius * (math.cos(u) * node + math.sin(u) * ahead),
                           speed * (-math.sin(u) * node + math.cos(u) * ahead)])


class _Hand:
    """Red flying the Hohmann pair, propagated here: three legs, each burn in-track at its state then."""

    def __init__(self) -> None:
        self.red0 = _circular(_R1, 0.0)
        coast = _leg(self.red0, 0.0, _BURN_1_S)
        self.pre1 = coast(_BURN_1_S)
        transfer = _leg(_in_track(self.pre1, _DV1), _BURN_1_S, _BURN_2_S)
        after = _leg(_in_track(transfer(_BURN_2_S), _DV2), _BURN_2_S, _SPAN_S + _BURN_2_S)
        self.legs = ((0.0, _BURN_1_S, coast), (_BURN_1_S, _BURN_2_S, transfer), (_BURN_2_S, math.inf, after))

    def __call__(self, t: float) -> np.ndarray:
        return next(leg(t) for t0, t1, leg in self.legs if t0 <= t < t1)


@pytest.fixture(scope="module")
def hand() -> _Hand:
    return _Hand()


def _pair(hand: _Hand, **spread: Any) -> tuple[ManoeuvreHypothesis, ManoeuvreHypothesis]:
    """The Hohmann pair as the engine takes it: burn 1 from red's own state, burn 2 with *spread* of its own."""
    first = ManoeuvreHypothesis(_START + timedelta(seconds=_BURN_1_S), _DV1, 0.0, _DV1, 0.0, hand.pre1, **_STILL)
    second = ManoeuvreHypothesis(_START + timedelta(seconds=_BURN_2_S), _DV2, 0.0, _DV2, 0.0, hand.pre1,
                                 **{**_STILL, **spread})
    return first, second


def _window(start_s: float = 0.0, span_s: float = _SPAN_S) -> SeparationWindow:
    return SeparationWindow(_START + timedelta(seconds=start_s), span_s, 30.0)


def _hand_miss(red: Any, blue: Any, span_s: float, offset_s: float = 0.0) -> float:
    """The smallest separation of two hand-propagated objects over *span_s*, red timed from *offset_s*."""
    grid = np.arange(0.0, span_s + 1.0, 5.0)
    seps = [float(np.linalg.norm(red(offset_s + t)[:3] - blue(t)[:3])) for t in grid]
    k = int(np.argmin(seps))
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    found = minimize_scalar(lambda t: float(np.linalg.norm(red(offset_s + t)[:3] - blue(t)[:3])), bounds=(lo, hi),
                            method="bounded", options={"xatol": 1e-6})
    return float(found.fun)


def _blue_near_arrival() -> np.ndarray:
    """A blue on the 1,200 km circle, placed so red arrives close to it."""
    u_arrive = math.degrees(math.pi + _BURN_1_S * math.sqrt(MU_EARTH / _R1**3))
    return _circular(_R2, u_arrive - math.degrees(math.sqrt(MU_EARTH / _R2**3) * _BURN_2_S) + 0.05)


_AFTER_BOTH_S = _BURN_2_S + 300.0


def _after_both(hand: _Hand) -> tuple[np.ndarray, SeparationWindow]:
    """A 2 h window starting 5 min after burn 2, and a blue 0.2 deg ahead of red on the 1,200 km circle then."""
    red_then = hand(_AFTER_BOTH_S)
    radial = red_then[:3] / np.linalg.norm(red_then[:3])
    cross = np.cross(red_then[:3], red_then[3:]) / np.linalg.norm(np.cross(red_then[:3], red_then[3:]))
    ahead, angle = np.cross(cross, radial), math.radians(0.2)
    blue0 = np.concatenate([_R2 * (math.cos(angle) * radial + math.sin(angle) * ahead),
                            math.sqrt(MU_EARTH / _R2) * (-math.sin(angle) * radial + math.cos(angle) * ahead)])
    return blue0, _window(_AFTER_BOTH_S, 7200.0)


# ── The nominal arc and the sampled series fly both burns as the hand propagation does ──

class TestAgainstAnIndependentPropagation:
    def test_the_nominal_arc_flies_both_burns(self, hand: _Hand) -> None:
        first, second = _pair(hand)
        arc = nominal_red_arc(first, _window(), [second])
        assert arc is not None
        worst = max(float(np.linalg.norm(arc(t)[:3] - hand(t)[:3])) for t in np.linspace(0.0, _SPAN_S, 37))
        assert worst < 0.001   # km
        # Burn 1 alone leaves red on the transfer ellipse, kilometres from where both burns put it.
        alone = nominal_red_arc(first, _window())
        assert alone is not None
        assert np.linalg.norm(alone(_SPAN_S)[:3] - hand(_SPAN_S)[:3]) > 10.0

    def test_a_sampled_series_with_no_spread_misses_by_what_the_hand_propagation_does(self, hand: _Hand) -> None:
        first, second = _pair(hand)
        blue0 = _blue_near_arrival()
        series = run_separation_series(first, BlueTrack(blue0, 0.0, _START), _window(), red_then=[second])
        expected = _hand_miss(hand, _leg(blue0, 0.0, _SPAN_S), _SPAN_S)
        assert series.n_failed == 0
        assert series.miss_km_p50 == pytest.approx(expected, abs=0.005)

    def test_a_window_after_both_burns_starts_red_from_its_first_burn(self, hand: _Hand) -> None:
        # Both burns before the window start: the chained arc runs from burn 1, not from the window start.
        blue0, window = _after_both(hand)
        first, second = _pair(hand)
        series = run_separation_series(first, BlueTrack(blue0, 0.0, window.start_utc), window, red_then=[second])
        expected = _hand_miss(hand, _leg(blue0, 0.0, window.span_s), window.span_s, offset_s=_AFTER_BOTH_S)
        assert series.miss_km_p50 == pytest.approx(expected, abs=0.01)

    def test_our_burn_is_sized_against_red_flying_both_burns(self, hand: _Hand) -> None:
        # After both burns, burn 1 alone leaves red tens of km from where both burns put it, so the closest
        # approach our burn is sized on names which red it flew.
        blue0, window = _after_both(hand)
        first, second = _pair(hand)
        request = BurnRequest("0", 60.0, 30.0, 0.01, BurnAxis.IN_TRACK)
        blue = BlueTrack(blue0, 0.0, window.start_utc)
        sized = hypothesis_response_plan(first, blue, window, [request], then=[second])
        alone = hypothesis_response_plan(first, blue, window, [request])
        assert sized is not None and alone is not None
        before = sized[0].before.approach.miss_km   # type: ignore[union-attr]
        expected = _hand_miss(hand, _leg(blue0, 0.0, window.span_s), window.span_s, offset_s=_AFTER_BOTH_S)
        assert before == pytest.approx(expected, abs=0.01)
        assert abs(alone[0].before.approach.miss_km - expected) > 1.0   # type: ignore[union-attr]


# ── Each later burn's own draws reach the arc ──

def _misses(hand: _Hand, **spread: Any) -> np.ndarray:
    first, second = _pair(hand, **spread)
    blue0 = _blue_near_arrival()
    series = run_separation_series(first, BlueTrack(blue0, 0.0, _START), _window(), red_then=[second])
    assert series.n_failed == 0
    return np.array([a.miss_km for a in series.approaches])


class TestEachLaterBurnDrawsItsOwnSpread:
    def test_with_no_spread_every_sample_misses_alike(self, hand: _Hand) -> None:
        assert np.ptp(_misses(hand)) < 1e-9

    def test_its_timing_is_drawn_per_sample(self, hand: _Hand) -> None:
        # Burn 1 has no spread at all, so only burn 2's own timing draw, sample by sample, can spread the misses.
        misses = _misses(hand, epoch_1sigma_seconds=60.0)
        assert np.ptp(misses) > 0.01

    def test_its_b_star_is_drawn_per_sample(self) -> None:
        # Low enough for drag: burn 2's B* draw alone, after it, spreads the samples.
        red0 = _circular(R_EARTH + 400.0, 0.0)
        first = ManoeuvreHypothesis(_START + timedelta(seconds=60.0), 0.001, 0.0, 0.001, 0.0, red0,
                                    **{**_STILL, "bstar_post": 1e-4})
        second = dataclasses.replace(first, epoch_utc=_START + timedelta(seconds=300.0), bstar_1sigma=5e-4,
                                     random_seed=11)
        blue0 = _circular(R_EARTH + 400.0, 0.4)
        series = run_separation_series(first, BlueTrack(blue0, 0.0, _START), _window(0.0, 7200.0), red_then=[second])
        misses = np.array([a.miss_km for a in series.approaches])
        assert np.ptp(misses) > 1e-6

    def test_the_nominal_flies_each_later_burns_own_b_star(self) -> None:
        red0 = _circular(R_EARTH + 400.0, 0.0)
        first = ManoeuvreHypothesis(_START + timedelta(seconds=60.0), 0.001, 0.0, 0.001, 0.0, red0,
                                    **{**_STILL, "bstar_post": 1e-4})
        later = dataclasses.replace(first, epoch_utc=_START + timedelta(seconds=300.0))
        same = nominal_red_arc(first, _window(0.0, 7200.0), [later])
        heavier = nominal_red_arc(first, _window(0.0, 7200.0), [dataclasses.replace(later, bstar_post=1e-2)])
        assert same is not None and heavier is not None
        assert np.linalg.norm(same(7200.0)[:3] - heavier(7200.0)[:3]) > 1e-3   # km


# ── The burns a sample makes ──

class TestTheBurnsASampleMakes:
    def _unburnt(self, hand: _Hand) -> Any:
        first, _second = _pair(hand)
        return _unburnt_arc(first, 0.0, _SPAN_S, _BURN_1_S)

    def test_a_later_burn_drawn_before_the_first_is_made_at_the_first(self, hand: _Hand) -> None:
        unburnt = self._unburnt(hand)
        burn = np.array([0.0, _DV1, 0.0])
        early = _chained_red(unburnt, (RedBurn(_BURN_1_S, burn, 0.0), RedBurn(_BURN_1_S - 120.0, burn, 0.0)), 0.0,
                             _window())
        at_first = _chained_red(unburnt, (RedBurn(_BURN_1_S, burn, 0.0), RedBurn(_BURN_1_S, burn, 0.0)), 0.0,
                                _window())
        assert early is not None and at_first is not None
        for t in (_BURN_1_S - 60.0, _BURN_1_S + 600.0, _SPAN_S):
            assert np.allclose(early(t), at_first(t), atol=1e-9)

    def test_a_transfer_starting_at_the_end_of_the_span_leaves_red_unburnt(self, hand: _Hand) -> None:
        unburnt = self._unburnt(hand)
        burn = np.array([0.0, _DV1, 0.0])
        red = _chained_red(unburnt, (RedBurn(_SPAN_S, burn, 0.0), RedBurn(_SPAN_S + 60.0, burn, 0.0)), 0.0,
                           _window())
        assert red is unburnt

    def test_a_kept_sample_holds_the_later_burn_still_to_come(self, hand: _Hand) -> None:
        # A turn boundary between the two burns keeps burn 2 as still to come, so a next turn would make it.
        first, second = _pair(hand)
        blue0 = _blue_near_arrival()
        boundary = _BURN_1_S + 600.0
        series = run_separation_series(first, BlueTrack(blue0, 0.0, _START), _window(), keep_at_s=[boundary],
                                       red_then=[second])
        assert series.kept is not None
        pending = series.kept.pending[0]
        assert len(pending) == 1 and pending[0].at_s == pytest.approx(_BURN_2_S - boundary)
