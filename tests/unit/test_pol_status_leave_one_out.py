"""The latest manoeuvre is scored against the ones before it.

Audit F-026. The latest delta-V was scored against a mean and standard
deviation that already included it. One member of a sample of n can sit at
most (n - 1) / sqrt(n) sample deviations from the mean (Samuelson's
inequality), so ANOMALOUS (z > 3) could not happen below n = 11 and CAUTION
(z > 2) below n = 6: an object whose latest burn was 100 times its only
earlier one read NORMAL.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from spectre.astro.pattern_of_life import _STATUS_MIN_PRIOR, _pol_status_for_history
from tests.unit.test_pol_status_ladder import _BURN, _manoeuvre


def _history(earlier: list[float], latest: float) -> list:
    return [_manoeuvre(dv) for dv in [*earlier, latest]]


@pytest.mark.parametrize("n_earlier", range(1, 12))
def test_a_burn_a_hundred_times_the_rest_is_anomalous_once_there_is_a_history(n_earlier: int) -> None:
    # Earlier burns of about 1 m/s with a little spread; the latest is 100 m/s.
    earlier = [0.001 * (1.0 + 0.05 * (k % 3)) for k in range(n_earlier)]
    status, reason = _pol_status_for_history(_BURN + timedelta(days=1), _history(earlier, 0.1))
    if n_earlier < _STATUS_MIN_PRIOR:
        assert status == "INSUFFICIENT"
        assert str(_STATUS_MIN_PRIOR) in reason
    else:
        assert status == "ANOMALOUS", f"{n_earlier} earlier manoeuvres"


def test_the_minimum_history_is_small_enough_to_matter() -> None:
    assert 2 <= _STATUS_MIN_PRIOR <= 5


def test_a_spreadless_history_still_flags_a_departure_from_it() -> None:
    status, _ = _pol_status_for_history(_BURN + timedelta(days=1), _history([0.001] * 4, 0.1))
    assert status == "ANOMALOUS"


def test_a_burn_like_the_rest_is_normal() -> None:
    status, _ = _pol_status_for_history(_BURN + timedelta(days=1), _history([0.001, 0.0011, 0.0009, 0.001], 0.00105))
    assert status == "NORMAL"


def test_an_old_latest_burn_is_still_normal_whatever_the_history() -> None:
    status, _ = _pol_status_for_history(_BURN + timedelta(days=30), _history([0.001], 0.1))
    assert status == "NORMAL"
