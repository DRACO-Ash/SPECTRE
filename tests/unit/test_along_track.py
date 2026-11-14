"""Shifting an element set along track, and the error model behind the delta-V band (SPC-005)."""

from __future__ import annotations

import numpy as np
import pytest

from spectre.astro.along_track import _checksum, position_error_km, shift_along_track
from spectre.astro.propagator import TLEOrbit
from spectre.web.elsets import _epoch_of
from tests.integration.test_all_intercepts_ranking import _RED_GEO
from tests.unit.test_astro import ISS_TLE


@pytest.mark.parametrize("tle", [_RED_GEO, ISS_TLE])
@pytest.mark.parametrize("km", [5.0, -5.0, 20.0])
def test_the_object_moves_by_the_distance_asked_along_its_motion(tle: str, km: float) -> None:
    epoch = _epoch_of(tle)
    assert epoch is not None
    base, moved = TLEOrbit(tle).propagate(epoch), TLEOrbit(shift_along_track(tle, km)).propagate(epoch)
    offset = moved.r - base.r
    # The mean anomaly is written to 4 decimals of a degree: 0.07 km at GEO,
    # 0.01 km in LEO; the rest is the chord against the arc.
    assert float(np.linalg.norm(offset)) == pytest.approx(abs(km), abs=0.15)
    assert np.sign(float(np.dot(offset, base.v))) == np.sign(km)


def test_the_shifted_set_carries_a_valid_checksum() -> None:
    line2 = shift_along_track(ISS_TLE, 7.0).splitlines()[-1]
    assert len(line2) == 69
    assert int(line2[68]) == _checksum(line2)


def test_nothing_but_the_mean_anomaly_changes() -> None:
    before = ISS_TLE.strip().splitlines()[-1]
    after = shift_along_track(ISS_TLE, 7.0).splitlines()[-1]
    assert before[:43] == after[:43] and before[51:68] == after[51:68]
    assert before[43:51] != after[43:51]


@pytest.mark.parametrize(("age", "regime", "expected"), [
    (0.0, "LEO", 1.0), (2.0, "LEO", 5.0), (2.0, "MEO", 5.0), (0.0, "GEO", 2.0), (3.0, "GEO", 5.0), (3.0, "deep", 5.0),
    (-1.0, "LEO", 1.0),
])
def test_the_error_grows_with_age_slower_where_orbits_change_slowly(age: float, regime: str, expected: float) -> None:
    assert position_error_km(age, regime) == pytest.approx(expected)
