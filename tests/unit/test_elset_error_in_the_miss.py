"""Element-set error in the closest approach (SPC-202, evaluation finding F-11, High).

The miss payoff was an SGP4 point miss (computed cells) or a P5 over burn dispersions only (sampled cells); the
element sets' own error, which spectre/astro/along_track.py puts at 1 km plus 2 km a day in LEO and 2 km plus 1 km a
day at GEO, never entered it, so bands read tighter than the inputs allow.

Now each sampled draw also moves each object along its orbit by an error drawn from that model at its element set's
age at the scenario epoch, seeded per sample and side, and a computed miss carries a band: the miss less and plus
both sets' error at the closest approach in quadrature, with the score reading the closer edge.

The geometry here is co-orbital: blue on the plane-change case's blue orbit, red the same element set moved 20 km
ahead along track, and no burn and no spread, so every sample's miss is 20 km plus red's draw less blue's.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta

import numpy as np
import pytest

from spectre.astro import monte_carlo as mc
from spectre.astro.along_track import position_error_km, shift_along_track
from spectre.astro.monte_carlo import (
    ElsetError,
    ManoeuvreHypothesis,
    SeparationWindow,
    elset_offsets_km,
    elset_state,
    run_separation_series,
)
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE

_AHEAD_KM = 20.0
_BLUE_TLE = PLANE_CHANGE.blue_tle
_RED_TLE = shift_along_track(_BLUE_TLE, _AHEAD_KM)
_WINDOW = SeparationWindow(EPOCH, 1800.0)
_SEED = 42


def _still(n: int, *, seed: int = _SEED) -> ManoeuvreHypothesis:
    """Red as its element set stands, no burn and no spread, on blue's drag, *n* samples."""
    red = elset_state(_RED_TLE, EPOCH)
    assert red is not None
    return ManoeuvreHypothesis(
        epoch_utc=EPOCH, delta_v_magnitude_km_s=0.0,
        delta_v_radial=0.0, delta_v_in_track=1.0, delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=red.state_eci_km.copy(),
        delta_v_magnitude_1sigma_km_s=0.0, delta_v_pointing_1sigma_deg=0.0, epoch_1sigma_seconds=0.0,
        bstar_post=red.bstar, bstar_1sigma=0.0, n_samples=n, random_seed=seed,
    )


def _blue() -> object:
    blue = elset_state(_BLUE_TLE, EPOCH)
    assert blue is not None
    return blue


class TestEachSampleDrawsBothObjectsErrors:
    def test_each_sample_misses_by_its_own_draws(self) -> None:
        """20 km plus red's draw along track less blue's, sample by sample: the series reads the moved objects."""
        error = ElsetError(red_km=1.0, blue_km=3.0)
        series = run_separation_series(_still(40), _blue(), _WINDOW, elset_error=error)  # type: ignore[arg-type]
        offsets = elset_offsets_km(error, _SEED, 40)
        expected = _AHEAD_KM + offsets[:, 0] - offsets[:, 1]
        assert series.n_failed == 0
        assert [a.miss_km for a in series.approaches] == pytest.approx(expected.tolist(), abs=0.05)
        assert series.elset_error == error

    def test_with_no_error_the_series_is_exactly_as_it_was(self) -> None:
        """No error asked for, or none to draw, changes nothing: the old series, figure for figure."""
        before = run_separation_series(_still(5), _blue(), _WINDOW)  # type: ignore[arg-type]
        zero = run_separation_series(_still(5), _blue(), _WINDOW, elset_error=ElsetError(0.0, 0.0))  # type: ignore[arg-type]
        assert [a.miss_km for a in zero.approaches] == [a.miss_km for a in before.approaches]
        assert before.elset_error is None

    def test_the_spread_is_both_errors_in_quadrature(self) -> None:
        """With no burn spread, the misses' spread is the two draws' combined: sqrt(1 + 3 squared) km."""
        series = run_separation_series(_still(300), _blue(), _WINDOW, elset_error=ElsetError(1.0, 3.0))  # type: ignore[arg-type]
        assert series.miss_km_std == pytest.approx(math.hypot(1.0, 3.0), rel=0.1)


class TestTheDrawsAreRepeatable:
    def test_the_same_seed_gives_the_same_series(self) -> None:
        error = ElsetError(2.0, 2.0)
        one = run_separation_series(_still(10), _blue(), _WINDOW, elset_error=error)  # type: ignore[arg-type]
        two = run_separation_series(_still(10), _blue(), _WINDOW, elset_error=error)  # type: ignore[arg-type]
        assert [a.miss_km for a in one.approaches] == [a.miss_km for a in two.approaches]

    def test_each_sample_and_side_has_its_own_seed(self) -> None:
        """Sample k's draw is the same whatever the sample count, and one side's error never moves the other's draw."""
        few, many = elset_offsets_km(ElsetError(1.0, 1.0), 7, 5), elset_offsets_km(ElsetError(1.0, 1.0), 7, 50)
        assert few.tolist() == many[:5].tolist()
        wider_red = elset_offsets_km(ElsetError(4.0, 1.0), 7, 5)
        assert wider_red[:, 1].tolist() == few[:, 1].tolist()
        assert wider_red[:, 0].tolist() == pytest.approx((4.0 * few[:, 0]).tolist())

    def test_another_seed_draws_again(self) -> None:
        assert elset_offsets_km(ElsetError(1.0, 1.0), 1, 5).tolist() != elset_offsets_km(ElsetError(1.0, 1.0), 2, 5).tolist()

    def test_the_draws_are_apart_from_the_burn_draws(self) -> None:
        """The burn spread is drawn from the hypothesis's seed alone; the element-set draws from their own stream."""
        offsets = elset_offsets_km(ElsetError(1.0, 1.0), _SEED, 200)
        burn = np.random.default_rng(_SEED).normal(size=200)
        assert abs(float(np.corrcoef(offsets[:, 0], burn)[0, 1])) < 0.2


class TestTheModelsRate:
    @pytest.mark.parametrize(("regime", "per_day"), [("LEO", 2.0), ("GEO", 1.0)])
    def test_two_days_of_age_add_the_models_rate(self, regime: str, per_day: float) -> None:
        """The 1 sigma drawn is along_track.position_error_km at the age read: the model's rate, a day at a time."""
        assert position_error_km(2.0, regime) - position_error_km(0.0, regime) == pytest.approx(2.0 * per_day)


class TestTheArcsRunFarEnough:
    def test_an_orbit_that_is_not_closed_pads_at_its_speed_now(self) -> None:
        """Past escape speed there is no apogee to be slowest at, so the padding reads the speed it has."""
        state = np.array([7000.0, 0.0, 0.0, 0.0, 11.0, 0.0])
        assert mc._slowest_km_s(state) == pytest.approx(11.0)
        assert mc._pad_s(np.array([22.0]), state) == pytest.approx(2.0 + mc._PAD_MARGIN_S)

    def test_an_elliptical_orbit_pads_at_its_apogee_speed(self) -> None:
        red = elset_state(_RED_TLE, EPOCH)
        assert red is not None
        slowest = mc._slowest_km_s(red.state_eci_km)
        assert 0.0 < slowest <= float(np.linalg.norm(red.state_eci_km[3:]))

    def test_a_state_moved_along_its_orbit_is_where_its_arc_puts_it(self) -> None:
        red = elset_state(_RED_TLE, EPOCH)
        assert red is not None
        moved = mc.moved_states(red.state_eci_km, red.bstar, np.array([0.0, 7.5]))
        assert moved is not None
        assert moved[0].tolist() == pytest.approx(red.state_eci_km.tolist())
        assert float(np.linalg.norm(moved[1][:3] - red.state_eci_km[:3])) == pytest.approx(7.5, abs=0.01)

    def test_a_state_below_the_floor_cannot_be_moved(self) -> None:
        under = np.array([6400.0, 0.0, 0.0, 0.0, 7.9, 0.0])
        assert mc.moved_states(under, 1e-4, np.array([1.0])) is None

    def test_an_arc_that_cannot_be_had_moves_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        red = elset_state(_RED_TLE, EPOCH)
        assert red is not None
        monkeypatch.setattr(mc, "_padded_arc", lambda *_: None)
        assert mc.moved_states(red.state_eci_km, red.bstar, np.array([1.0])) is None


def test_a_window_later_than_the_tracks_is_still_refused() -> None:
    """The window check stands with an error asked for: a blue track from another instant is refused first."""
    blue = elset_state(_BLUE_TLE, EPOCH + timedelta(seconds=60))
    assert blue is not None
    with pytest.raises(ValueError, match="not at the window start"):
        run_separation_series(_still(2), blue, _WINDOW, elset_error=ElsetError(1.0, 1.0))
    assert dataclasses.is_dataclass(_still(1))
