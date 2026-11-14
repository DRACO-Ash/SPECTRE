"""A separation series carried from turn to turn, sample by sample (SPC-140).

A game tree's turn 2 starts where turn 1 left each sample: run_separation_series keeps each sample's red state and
B* at the turn boundary, with its smallest separation from each blue within the turn, and continue_series carries
each sample on from there, burning again with a spread drawn afresh from where that sample is. Sample k of turn 2
is sample k of turn 1, so a path's closest approach pairs each sample with itself.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import timedelta

import numpy as np
import pytest

from spectre.astro import monte_carlo
from spectre.astro.monte_carlo import (
    ContinuedRed,
    Kept,
    ManoeuvreHypothesis,
    RedBurn,
    ReenteredError,
    SeparationWindow,
    TurnBurn,
    _dense_arc,
    continue_series,
    elset_state,
    generate_samples,
    nominal_continued_arc,
    rk45_arc,
    run_separation_series,
)
from spectre.domain.decision_tree import paired_minima
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE
from tests.unit.test_decision_sampled import _evasive

_BLUE = elset_state(COPLANAR_LEO.blue_tle, EPOCH)
assert _BLUE is not None
_WINDOW = SeparationWindow(EPOCH, 3600.0)


def _blue_arc(span_s: float = 3600.0) -> Callable[[float], np.ndarray]:
    arc = rk45_arc(_BLUE.state_eci_km, span_s, _BLUE.bstar)
    assert arc is not None
    return arc


def _ensemble() -> np.ndarray:
    """Two red samples on blue's orbit: sample 0 5 km radially above it, sample 1 500 km above."""
    starts = np.tile(_BLUE.state_eci_km, (2, 1))
    radial = _BLUE.state_eci_km[:3] / np.linalg.norm(_BLUE.state_eci_km[:3])
    starts[0, :3] += 5.0 * radial
    starts[1, :3] += 500.0 * radial
    return starts


def _in_track(n: int = 50, *, seed: int = 7) -> ManoeuvreHypothesis:
    return ManoeuvreHypothesis(
        epoch_utc=EPOCH, delta_v_magnitude_km_s=0.002, delta_v_radial=0.0, delta_v_in_track=0.002,
        delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=np.zeros(6), n_samples=n, random_seed=seed,
    )


class TestSamplesStayPairedAcrossTurns:
    def test_each_sample_continues_from_its_own_state(self) -> None:
        """8: sample 0 stays near blue and sample 1 far, in sample order, and each is kept where its arc is."""
        starts = _ensemble()
        out = continue_series(ContinuedRed(starts, np.full(2, 1e-4)), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,))
        (series,) = out.series
        near, far = (a.miss_km for a in series.approaches)
        assert near < 10.0
        assert far > 400.0
        assert out.kept is not None
        for k in range(2):
            arc = _dense_arc(starts[k], 0.0, 3600.0, 1e-4)
            assert arc is not None
            np.testing.assert_allclose(out.kept.red[k, 0], arc(1800.0), atol=1e-9)
        np.testing.assert_array_equal(out.kept.bstar, [1e-4, 1e-4])
        assert out.kept.slice_min_km.shape == (1, 2)
        assert out.kept.slice_min_km[0, 0] < 10.0
        assert out.kept.slice_min_km[0, 1] > 400.0

    def test_a_path_pairs_each_samples_turns(self) -> None:
        """8: turn 1's minima with turn 2's, sample k with sample k; crossed, both samples would read near."""
        starts = _ensemble()
        one = continue_series(ContinuedRed(starts, np.full(2, 1e-4)), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,))
        assert one.kept is not None
        window2 = SeparationWindow(EPOCH + timedelta(seconds=1800.0), 1800.0)
        blue2 = _blue_arc(3600.0)
        two = continue_series(
            ContinuedRed(one.kept.red[:, 0], one.kept.bstar), (lambda t: blue2(t + 1800.0),), window2,
        )
        turn_two = np.array([a.miss_km for a in two.series[0].approaches])
        paired = paired_minima(one.kept.slice_min_km[0], turn_two)
        assert paired[0] < 10.0
        assert paired[1] > 400.0
        crossed = paired_minima(one.kept.slice_min_km[0], turn_two[::-1])
        assert crossed[1] < 50.0

    def test_a_single_computed_figure_stands_for_every_sample(self) -> None:
        """9: a path that was computed until red was sampled pairs its one figure with each sample."""
        np.testing.assert_array_equal(paired_minima(np.array([12.0]), np.array([30.0, 8.0])), [12.0, 8.0])
        np.testing.assert_array_equal(paired_minima(np.array([12.0, 30.0]), np.array([30.0, 12.0])), [12.0, 12.0])


class TestAContinuedBurn:
    def test_each_sample_burns_with_its_own_spread_drawn_from_its_own_state(self) -> None:
        """Same inputs, same draws; a burn moves the samples apart, and its timing is clamped to the turn's start:
        a draw before it burns at the start, never in the turn before."""
        starts = np.tile(_BLUE.state_eci_km, (50, 1))
        burn = TurnBurn(_in_track(), 0.0)
        a = continue_series(ContinuedRed(starts, np.full(50, 1e-4), burn), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,))
        b = continue_series(ContinuedRed(starts, np.full(50, 1e-4), burn), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,))
        assert a.series[0].approaches == b.series[0].approaches
        assert a.kept is not None
        assert np.ptp(a.kept.red[:, 0, 0]) > 0.01
        assert not np.allclose(a.kept.bstar, 1e-4)
        assert a.series[0].n_failed == 0
        assert a.series[0].n_samples_run == 50
        draws = generate_samples(_in_track())
        assert 10 <= int((draws[:, 3] < 0.0).sum()) <= 40
        for k, draw in enumerate(draws):
            at_s = max(float(draw[3]), 0.0)
            before = _dense_arc(_BLUE.state_eci_km, 0.0, at_s, 1e-4)
            assert before is not None
            state = before(at_s).copy()
            state[3:] += monte_carlo._ric_to_eci_rotation(state[:3], state[3:]) @ draw[:3]
            after = _dense_arc(state, at_s, 1800.0, _in_track().bstar_post + float(draw[4]))
            assert after is not None
            np.testing.assert_allclose(a.kept.red[k, 0, :3], after(1800.0)[:3], atol=1e-4, rtol=0.0)

    def test_the_nominal_arc_burns_the_undispersed_delta_v(self) -> None:
        burn = TurnBurn(_in_track(), 600.0)
        arc, bstar = nominal_continued_arc(_BLUE.state_eci_km, 1e-4, burn, 3600.0)
        coast = _dense_arc(_BLUE.state_eci_km, 0.0, 3600.0, 1e-4)
        assert coast is not None
        np.testing.assert_allclose(arc(300.0), coast(300.0), atol=1e-9)
        dv = arc(600.0 + 1e-6)[3:] - coast(600.0 + 1e-6)[3:]
        at = coast(600.0)
        in_track = monte_carlo._ric_to_eci_rotation(at[:3], at[3:]) @ np.array([0.0, 0.002, 0.0])
        np.testing.assert_allclose(dv, in_track, atol=1e-6, rtol=0.0)
        assert bstar == _in_track().bstar_post
        still, kept = nominal_continued_arc(_BLUE.state_eci_km, 1e-4, None, 3600.0)
        np.testing.assert_allclose(still(3600.0), coast(3600.0), atol=1e-9)
        assert kept == 1e-4

    def test_a_sample_that_reenters_fails_alone(self) -> None:
        starts = _ensemble()
        starts[1, :3] *= 6400.0 / np.linalg.norm(starts[1, :3])   # inside the atmosphere floor
        out = continue_series(ContinuedRed(starts, np.full(2, 1e-4)), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,))
        assert out.series[0].n_failed == 1
        assert out.series[0].n_reentered == 1
        assert out.kept is not None
        assert math.isnan(out.kept.slice_min_km[0, 1])

    def test_a_window_the_helper_refuses_is_refused_first(self) -> None:
        with pytest.raises(ValueError, match="separation window"):
            continue_series(ContinuedRed(_ensemble(), np.full(2, 1e-4)), (_blue_arc(),), SeparationWindow(EPOCH, 0.0))


class TestTheFirstTurnKeepsItsBoundary:
    def test_keeping_a_boundary_changes_no_figure(self) -> None:
        """The series with a boundary kept is the series without it, plus each sample's state there; each sample's
        slice minimum is its own arc's, searched to the boundary and no further."""
        hypothesis = _evasive(50).hypothesis
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        plain = run_separation_series(hypothesis, blue, _WINDOW)
        kept = run_separation_series(hypothesis, blue, _WINDOW, keep_at_s=(1800.0,))
        assert plain.approaches == kept.approaches
        assert plain.kept is None
        assert kept.kept is not None
        assert kept.kept.red.shape == (50, 1, 6)
        assert kept.kept.slice_min_km.shape == (1, 50)
        for k, approach in enumerate(kept.approaches):
            slice_min = float(kept.kept.slice_min_km[0, k])
            assert slice_min >= approach.miss_km - 1e-6
            if approach.tca_s < 1800.0 - 60.0:
                assert slice_min == pytest.approx(approach.miss_km, abs=1e-6)
        early = run_separation_series(hypothesis, blue, _WINDOW, keep_at_s=(1000.0,)).kept
        assert early is not None
        draws = generate_samples(hypothesis)
        burn_s = (hypothesis.epoch_utc - EPOCH).total_seconds()
        unburnt = monte_carlo._unburnt_arc(hypothesis, monte_carlo._earliest_s(burn_s + draws[:, 3]), 3600.0, burn_s)
        blue_arc = _dense_arc(blue.state_eci_km, 0.0, 3600.0, blue.bstar)
        assert unburnt is not None and blue_arc is not None
        sliced = []
        for draw in draws:
            red = monte_carlo._sample_red(draw, unburnt, burn_s, hypothesis.bstar_post, _WINDOW)
            assert red is not None
            sliced.append(monte_carlo.searched_approach(red, blue_arc, SeparationWindow(EPOCH, 1000.0)).approach.miss_km)
        np.testing.assert_allclose(early.slice_min_km[0], sliced, atol=1e-9, rtol=0.0)
        misses = np.array([a.miss_km for a in kept.approaches])
        assert np.min(np.array(sliced) - misses) > 1.0   # the pass at about 1,411 s falls after the slice


class TestASolveThatFails:
    """A sample whose arc cannot be had fails alone, against every blue; the nominal arc is then None."""

    @pytest.mark.parametrize(
        ("failure", "burn"),
        [(ValueError("singular"), None), (None, None), (None, TurnBurn(_in_track(2), 600.0))],
        ids=["raised", "coast", "before the burn"],
    )
    def test_each_sample_fails_against_every_blue(
        self, failure: Exception | None, burn: TurnBurn | None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(*_: object) -> None:
            if failure is not None:
                raise failure

        blues = (_blue_arc(), _blue_arc())
        monkeypatch.setattr(monte_carlo, "_dense_arc", broken)
        out = continue_series(ContinuedRed(_ensemble(), np.full(2, 1e-4), burn), blues, _WINDOW)
        assert [s.n_failed for s in out.series] == [2, 2]
        assert [s.n_reentered for s in out.series] == [0, 0]

    def test_a_nominal_arc_that_reenters_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def reenters(*_: object) -> None:
            raise ReenteredError("below the floor")

        monkeypatch.setattr(monte_carlo, "_dense_arc", reenters)
        assert nominal_continued_arc(_BLUE.state_eci_km, 1e-4, TurnBurn(_in_track(), 600.0), 3600.0) is None
        monkeypatch.setattr(monte_carlo, "_dense_arc", lambda *_: None)
        assert nominal_continued_arc(_BLUE.state_eci_km, 1e-4, None, 3600.0) is None


def _late() -> ManoeuvreHypothesis:
    """plane_change's Evasive burning 0.49 h in, 1,764 s, 120 s 1-sigma: a third of its samples burn after 1,800 s."""
    hypothesis = cases.evasive(PLANE_CHANGE, n=50, offset_h=0.49).hypothesis
    assert hypothesis is not None
    return hypothesis.hypothesis


def _assert_carried_on(blue_start: np.ndarray, kept: Kept, *, boundary_s: float, end_s: float) -> None:
    """Carried on from the first boundary with the burns still to come, each sample is where its own arc put it at
    the second: a burn that falls after the boundary is made then, in the turn after, never dropped."""
    blue = _dense_arc(blue_start, 0.0, end_s + 100.0, 1e-4)
    assert blue is not None
    window = SeparationWindow(EPOCH + timedelta(seconds=boundary_s), end_s + 100.0 - boundary_s)
    on = continue_series(
        ContinuedRed(kept.red[:, 0], kept.bstar, None, kept.pending), (lambda t: blue(t + boundary_s),), window,
        keep_at_s=(end_s - boundary_s,),
    )
    assert on.kept is not None
    np.testing.assert_allclose(on.kept.red[:, 0, :3], kept.red[:, 1, :3], atol=1e-3, rtol=0.0)
    np.testing.assert_allclose(on.kept.bstar, [_bstar_after(p, b) for p, b in zip(kept.pending, kept.bstar, strict=True)])


def _bstar_after(pending: tuple[RedBurn, ...], bstar: float) -> float:
    """The B* a sample flies once its burns still to come are made."""
    return pending[-1].bstar_after if pending else bstar


class TestABurnPastTheBoundaryIsCarried:
    """A sample whose drawn burn time falls after the turn ends keeps that burn for the turn after."""

    def test_turn_one_keeps_each_late_samples_burn_for_turn_two(self) -> None:
        hypothesis = _late()
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        series = run_separation_series(hypothesis, blue, _WINDOW, keep_at_s=(1800.0, 3300.0))
        kept = series.kept
        assert kept is not None
        draws = generate_samples(hypothesis)
        burn_s = 1764.0 + draws[:, 3]
        late = burn_s > 1800.0
        assert 5 <= int(late.sum()) <= 45
        assert len(kept.pending) == 50
        for k, pending in enumerate(kept.pending):
            if not late[k]:
                assert pending == ()
                continue
            (burn,) = pending
            assert burn.at_s == pytest.approx(burn_s[k] - 1800.0)
            np.testing.assert_array_equal(burn.delta_v_ric_km_s, draws[k, :3])
            assert burn.bstar_after == pytest.approx(hypothesis.bstar_post + draws[k, 4])
            assert kept.bstar[k] == hypothesis.bstar_post
        _assert_carried_on(blue.state_eci_km, kept, boundary_s=1800.0, end_s=3300.0)

    def test_a_later_turn_keeps_its_late_burns_too(self) -> None:
        starts = np.tile(_BLUE.state_eci_km, (50, 1))
        starts[:, :3] += 20.0 * _BLUE.state_eci_km[:3] / np.linalg.norm(_BLUE.state_eci_km[:3])
        burn = TurnBurn(_late(), 1764.0)
        out = continue_series(
            ContinuedRed(starts, np.full(50, 1e-4), burn), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0, 3300.0),
        )
        assert out.kept is not None
        assert 5 <= sum(bool(p) for p in out.kept.pending) <= 45
        _assert_carried_on(_BLUE.state_eci_km, out.kept, boundary_s=1800.0, end_s=3300.0)

    def test_a_burn_past_the_end_of_the_span_is_never_made(self) -> None:
        """Held for the turn after, but that turn ends first: the sample coasts, as turn 1's arc does."""
        starts = np.tile(_BLUE.state_eci_km, (1, 1))
        late = RedBurn(5000.0, np.array([0.0, 0.01, 0.0]), 2e-4)
        out = continue_series(
            ContinuedRed(starts, np.full(1, 1e-4), None, ((late,),)), (_blue_arc(),), _WINDOW, keep_at_s=(1800.0,),
        )
        coast = _dense_arc(_BLUE.state_eci_km, 0.0, 3600.0, 1e-4)
        assert coast is not None
        assert out.kept is not None
        np.testing.assert_allclose(out.kept.red[0, 0], coast(1800.0), atol=1e-9, rtol=0.0)
        assert out.kept.pending == ((late._replace(at_s=3200.0),),)
        assert out.kept.bstar[0] == 1e-4


class TestACarriedBurnAndAFreshOne:
    """A sample that carries a burn from the turn before and draws a fresh one in this turn makes both, in order."""

    def test_both_burns_are_made(self) -> None:
        """Made in one turn, the two burns leave each sample where making them one turn at a time does."""
        starts = np.tile(_BLUE.state_eci_km, (2, 1))
        carried = RedBurn(300.0, np.array([0.0, 0.002, 0.0]), 2e-4)
        burn = TurnBurn(_in_track(2), 1200.0)
        both = continue_series(
            ContinuedRed(starts, np.full(2, 1e-4), burn, ((carried,), (carried,))), (_blue_arc(),), _WINDOW,
            keep_at_s=(3000.0,),
        )
        assert both.kept is not None
        fresh = [monte_carlo._drawn_burns(burn, draw)[0] for draw in generate_samples(_in_track(2))]
        assert all(600.0 < f.at_s < 3000.0 for f in fresh)
        first = continue_series(
            ContinuedRed(starts, np.full(2, 1e-4), None, ((carried,), (carried,))), (_blue_arc(),), _WINDOW,
            keep_at_s=(600.0,),
        )
        assert first.kept is not None
        rest = SeparationWindow(EPOCH + timedelta(seconds=600.0), 3000.0)
        then = continue_series(
            ContinuedRed(first.kept.red[:, 0], first.kept.bstar, None, tuple((f._replace(at_s=f.at_s - 600.0),) for f in fresh)),
            (lambda t: _blue_arc()(t + 600.0),), rest, keep_at_s=(2400.0,),
        )
        assert then.kept is not None
        np.testing.assert_allclose(both.kept.red[:, 0, :3], then.kept.red[:, 0, :3], atol=1e-3, rtol=0.0)
        np.testing.assert_allclose(both.kept.bstar, [f.bstar_after for f in fresh])
        coast = _dense_arc(_BLUE.state_eci_km, 0.0, 3000.0, 1e-4)
        assert coast is not None
        assert float(np.linalg.norm(both.kept.red[0, 0, :3] - coast(3000.0)[:3])) > 1.0


class TestProgress:
    def test_each_sample_ticks_once_and_the_last_reads_all_of_them(self) -> None:
        """The tick reads samples done of samples to do: 1 of 2, then 2 of 2, never n - 1 of n at the end."""
        ticks: list[tuple[int, int]] = []
        continue_series(
            ContinuedRed(_ensemble(), np.full(2, 1e-4)), (_blue_arc(),), _WINDOW,
            tick=lambda done, total: ticks.append((done, total)),
        )
        assert ticks == [(1, 2), (2, 2)]
